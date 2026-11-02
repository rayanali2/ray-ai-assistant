"""Official stream-json/JSONL event shapes, exercised through real fake processes."""

import json
import sys

import pytest
from pydantic import ValidationError

from ray.agents.base import AgentContext, AgentFinished
from ray.agents.planning import PlanningAgent
from ray.config import Settings
from ray.llm.base import CompletionRequest, LLMMessage, ProviderUnavailableError, ToolSpec
from ray.llm.providers.claude_cli import ClaudeCLIProvider
from ray.llm.providers.codex_cli import CodexCLIProvider
from ray.llm.registry import ProviderRegistry
from ray.tools.manager import AgentToolbox, ToolContext, get_manager

REQUEST = CompletionRequest(
    system="You are Ray.",
    messages=[
        LLMMessage(role="assistant", content="Earlier"),
        LLMMessage(role="user", content="hi"),
    ],
    tools=[ToolSpec(name="edit", description="Do not execute", parameters={})],
)
CLAUDE_EVENTS = [
    {"type": "system", "subtype": "init"},
    {
        "type": "stream_event",
        "event": {
            "type": "content_block_delta",
            "delta": {"type": "thinking_delta", "thinking": "private reasoning"},
        },
    },
    {
        "type": "stream_event",
        "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}},
    },
    {
        "type": "stream_event",
        "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": " Ray"}},
    },
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello Ray"}]}},
    {"type": "result", "subtype": "success", "is_error": False, "result": "Hello Ray"},
]
CODEX_EVENTS = [
    {"type": "thread.started", "thread_id": "test"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "0", "type": "reasoning", "text": "private"}},
    {"type": "item.started", "item": {"id": "1", "type": "agent_message", "text": "Hello"}},
    {"type": "item.completed", "item": {"id": "1", "type": "agent_message", "text": "Hello Ray"}},
    {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}},
]


def fake_cli(tmp_path, body):
    binary = tmp_path / "fake-cli"
    binary.write_text(f"#!{sys.executable}\nimport json, os, sys, time\n" + body)
    binary.chmod(0o755)
    return str(binary)


@pytest.mark.parametrize(
    ("cls", "events"),
    [
        (ClaudeCLIProvider, CLAUDE_EVENTS),
        (CodexCLIProvider, CODEX_EVENTS),
    ],
)
async def test_cli_complete_and_stream(tmp_path, cls, events):
    capture = tmp_path / "capture.json"
    binary = fake_cli(
        tmp_path,
        f"from pathlib import Path\nPath({str(capture)!r}).write_text(json.dumps("
        "{'args': sys.argv[1:], 'prompt': sys.stdin.read(), 'cwd': os.getcwd()}))\n"
        + "\n".join(f"print({json.dumps(event)!r}, flush=True)" for event in events),
    )
    provider = cls(binary=binary, model="chosen")
    assert provider.info().configured
    assert not provider.supports_tools()
    completion = await provider.complete(REQUEST)
    assert completion.text == "Hello Ray"
    assert completion.tool_calls == ()
    assert completion.model == "chosen"
    chunks = [chunk async for chunk in provider.stream(REQUEST)]
    assert "".join(chunk.text for chunk in chunks) == "Hello Ray"
    assert chunks[-1].is_final
    invocation = json.loads(capture.read_text())
    assert "system: You are Ray." in invocation["prompt"]
    assert "assistant: Earlier" in invocation["prompt"]
    assert "user: hi" in invocation["prompt"]
    assert invocation["cwd"] != str(tmp_path)
    assert "chosen" in invocation["args"]
    if cls is ClaudeCLIProvider:
        args = invocation["args"]
        assert args[args.index("--tools") + 1] == ""
        assert args[args.index("--system-prompt") + 1] == REQUEST.system
        assert "--strict-mcp-config" in args
        assert "--disable-slash-commands" in args
    else:
        assert "read-only" in invocation["args"]
        assert "--skip-git-repo-check" in invocation["args"]
        assert "--ignore-user-config" in invocation["args"]


@pytest.mark.parametrize("cls", [ClaudeCLIProvider, CodexCLIProvider])
@pytest.mark.parametrize(
    "body",
    [
        "sys.stdin.read(); sys.exit(7)",
        "sys.stdin.read(); print('Not logged in', file=sys.stderr)",
        "sys.stdin.read(); time.sleep(5)",
        "sys.stdin.read(); print('not json')",
        "sys.stdin.read()",
        "sys.stdin.read(); "
        "print(json.dumps({'type':'error', 'message':'authentication required'}))",
        "sys.stdin.read(); print(json.dumps({'type':'turn.failed','error':{'message':'failed'}}))",
    ],
)
async def test_cli_failure_falls_back(tmp_path, cls, body):
    provider = cls(binary=fake_cli(tmp_path, body), timeout_seconds=0.15)
    with pytest.raises(ProviderUnavailableError, match="Sign in"):
        await provider.complete(REQUEST)
    registry = ProviderRegistry(
        Settings(_env_file=None, llm_provider=provider.name, llm_fallback_provider="mock")
    )
    registry.register(provider.name, provider)
    assert (await registry.complete(REQUEST)).provider == "mock"
    chunks = [chunk async for chunk in registry.stream(REQUEST)]
    assert any("mock" in chunk.text for chunk in chunks)


@pytest.mark.parametrize("cls", [ClaudeCLIProvider, CodexCLIProvider])
async def test_missing_binary(tmp_path, cls):
    provider = cls(binary=str(tmp_path / "absent"))
    assert not provider.info().configured
    with pytest.raises(ProviderUnavailableError, match="executable not found"):
        await provider.complete(REQUEST)


async def test_claude_result_without_partial_events(tmp_path):
    provider = ClaudeCLIProvider(
        binary=fake_cli(
            tmp_path,
            "sys.stdin.read(); print(json.dumps({'type':'result','result':'Hi','is_error':False}))",
        )
    )
    assert (await provider.complete(REQUEST)).text == "Hi"


@pytest.mark.parametrize(
    ("cls", "event"),
    [
        (ClaudeCLIProvider, CLAUDE_EVENTS[2]),
        (CodexCLIProvider, CODEX_EVENTS[4]),
    ],
)
async def test_text_arrives_before_process_exit_and_no_midstream_fallback(tmp_path, cls, event):
    provider = cls(
        binary=fake_cli(
            tmp_path, f"sys.stdin.read(); print({json.dumps(event)!r}, flush=True); time.sleep(5)"
        ),
        timeout_seconds=0.3,
    )
    registry = ProviderRegistry(
        Settings(_env_file=None, llm_provider=provider.name, llm_fallback_provider="mock")
    )
    registry.register(provider.name, provider)
    stream = registry.stream(REQUEST)
    assert (await anext(stream)).text.startswith("Hello")
    with pytest.raises(ProviderUnavailableError):
        await anext(stream)


@pytest.mark.parametrize(
    ("fallback", "expected"),
    [
        ("ollama", ("gemini", "ollama", "mock")),
        (
            " claude_cli, codex_cli,ollama,claude_cli ",
            ("gemini", "claude_cli", "codex_cli", "ollama", "mock"),
        ),
        ("mock,codex_cli,mock", ("gemini", "codex_cli", "mock")),
        ("", ("gemini", "mock")),
        (None, ("gemini", "mock")),
    ],
)
def test_csv_chain(fallback, expected):
    settings = Settings(
        _env_file=None,
        llm_provider="gemini",
        llm_fallback_provider=fallback,
        llm_router_provider="codex_cli",
    )
    registry = ProviderRegistry(settings)
    assert registry.chain() == expected
    assert registry.chain("router")[0] == "codex_cli"


def test_unknown_csv_provider_rejected():
    with pytest.raises(ValidationError, match="Unknown LLM fallback"):
        Settings(_env_file=None, llm_fallback_provider="claude_cli,typo")


@pytest.mark.parametrize(
    ("cls", "events"),
    [
        (ClaudeCLIProvider, CLAUDE_EVENTS),
        (CodexCLIProvider, CODEX_EVENTS),
    ],
)
async def test_tool_agent_answers_without_cli_tool_support(tmp_path, cls, events, session, user_id):
    provider = cls(
        binary=fake_cli(
            tmp_path,
            "sys.stdin.read()\n"
            + "\n".join(f"print({json.dumps(event)!r}, flush=True)" for event in events),
        )
    )
    registry = ProviderRegistry(
        Settings(_env_file=None, llm_provider=provider.name, llm_fallback_provider=None)
    )
    registry.register(provider.name, provider)
    ctx = AgentContext(
        user_id=user_id,
        user_name="Test",
        message="Plan my week",
        history=[],
        tools=AgentToolbox(get_manager(), ToolContext(session=session, user_id=user_id)),
    )
    events = [event async for event in PlanningAgent(registry).run(ctx)]
    assert any(
        isinstance(event, AgentFinished) and event.content == "Hello Ray" for event in events
    )
    assert not ctx.tools.results
