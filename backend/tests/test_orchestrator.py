"""The pipeline, against a scripted provider (no network)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ray.agents.executive import to_speech
from ray.config import Settings
from ray.core.contracts import RayRequest
from ray.core.events import DoneEvent, ErrorEvent, StreamEvent, TokenEvent, TraceStreamEvent
from ray.core.orchestrator import Orchestrator
from ray.db.models import AgentActivity, Message
from ray.domain.enums import MessageRole, Modality
from ray.llm.base import ProviderUnavailableError, RateLimitedError
from ray.llm.registry import ProviderRegistry
from tests.fakes import FakeProvider


def _registry(provider: FakeProvider) -> ProviderRegistry:
    registry = ProviderRegistry(Settings(llm_provider="mock", llm_fallback_provider=None))
    registry.register("mock", provider)
    return registry


def _orchestrator(provider: FakeProvider, **settings: object) -> Orchestrator:
    return Orchestrator(
        providers=_registry(provider),
        settings=Settings(llm_provider="mock", llm_fallback_provider=None, **settings),  # type: ignore[arg-type]
    )


async def _collect(
    orchestrator: Orchestrator, session: AsyncSession, request: RayRequest
) -> list[StreamEvent]:
    return [event async for event in orchestrator.run(session, request, "Rayan")]


def _request(user_id: uuid.UUID, message: str = "hello", **kwargs: object) -> RayRequest:
    return RayRequest(user_id=user_id, message=message, **kwargs)  # type: ignore[arg-type]


async def test_events_arrive_in_pipeline_order(session: AsyncSession, user_id: uuid.UUID) -> None:
    events = await _collect(
        _orchestrator(FakeProvider(["Hi ", "there"])), session, _request(user_id)
    )

    stages = [e.stage for e in events if isinstance(e, TraceStreamEvent)]
    assert stages[:3] == ["memory", "routing", "agent"]
    assert "".join(e.text for e in events if isinstance(e, TokenEvent)) == "Hi there"
    assert isinstance(events[-1], DoneEvent)


async def test_fallback_trace_attributes_the_answer_not_the_preferred_provider(session, user_id):
    registry = ProviderRegistry(Settings(llm_provider="gemini", llm_fallback_provider="mock"))
    registry.register(
        "gemini",
        FakeProvider(name="gemini", fail_with=RateLimitedError("quota", provider="gemini")),
    )
    registry.register("mock", FakeProvider(name="mock", chunks=["canned"]))
    events = await _collect(Orchestrator(providers=registry), session, _request(user_id))
    agents = [e for e in events if isinstance(e, TraceStreamEvent) and e.stage == "agent"]
    assert agents and all(e.detail["provider"] == "mock" for e in agents)
    done = events[-1]
    assert isinstance(done, DoneEvent)
    saved = await session.get(Message, done.message_id)
    assert all(e["provider"] == "mock" for e in saved.trace["events"] if e["stage"] == "agent")


async def test_user_message_is_persisted_before_the_model_is_called(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    """A provider that dies must not take the user's words with it."""
    provider = FakeProvider(fail_with=ProviderUnavailableError("down", provider="mock"))
    events = await _collect(_orchestrator(provider), session, _request(user_id, "remember this"))

    assert isinstance(events[-1], ErrorEvent)
    stored = list((await session.execute(select(Message))).scalars())
    assert [m.content for m in stored] == ["remember this"]
    assert stored[0].role is MessageRole.USER


async def test_answer_is_persisted_with_trace_and_speech(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    events = await _collect(_orchestrator(FakeProvider(["Done."])), session, _request(user_id))
    done = events[-1]
    assert isinstance(done, DoneEvent)

    message = await session.get(Message, done.message_id)
    assert message is not None
    assert message.content == "Done."
    assert message.speech_text == "Done."
    assert message.agent_name == "executive"
    # The trace is recorded by the code that did the work, not narrated by the model.
    assert message.trace is not None
    assert [e["stage"] for e in message.trace["events"]][:3] == ["memory", "routing", "agent"]


async def test_conversation_continues_and_history_is_passed_to_the_model(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    provider = FakeProvider(["ok"])
    orchestrator = _orchestrator(provider)

    first = await _collect(orchestrator, session, _request(user_id, "one"))
    done = first[-1]
    assert isinstance(done, DoneEvent)
    await _collect(
        orchestrator, session, _request(user_id, "two", conversation_id=done.conversation_id)
    )

    # Second call sees turn one, and the current turn is not duplicated.
    second_request = provider.calls[-1]
    assert [m.content for m in second_request.messages] == ["one", "ok", "two"]


async def test_history_window_is_respected(session: AsyncSession, user_id: uuid.UUID) -> None:
    provider = FakeProvider(["ok"])
    orchestrator = _orchestrator(provider, history_window=2)

    conversation_id: uuid.UUID | None = None
    for index in range(3):
        events = await _collect(
            orchestrator, session, _request(user_id, f"m{index}", conversation_id=conversation_id)
        )
        done = events[-1]
        assert isinstance(done, DoneEvent)
        conversation_id = done.conversation_id

    assert len(provider.calls[-1].messages) <= 2


async def test_unknown_conversation_id_starts_a_new_one_instead_of_failing(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    events = await _collect(
        _orchestrator(FakeProvider()),
        session,
        _request(user_id, "hi", conversation_id=uuid.uuid4()),
    )
    assert isinstance(events[-1], DoneEvent)


async def test_voice_output_changes_the_prompt(session: AsyncSession, user_id: uuid.UUID) -> None:
    provider = FakeProvider(["ok"])
    await _collect(
        _orchestrator(provider),
        session,
        _request(user_id, "hi", output_modality=Modality.VOICE),
    )
    assert "spoken aloud" in provider.calls[-1].system


async def test_activity_is_logged_for_success_and_failure(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    await _collect(_orchestrator(FakeProvider(["ok"])), session, _request(user_id))
    await _collect(
        _orchestrator(FakeProvider(fail_with=RateLimitedError("quota", provider="mock"))),
        session,
        _request(user_id),
    )
    rows = list((await session.execute(select(AgentActivity))).scalars())
    assert sorted(row.success for row in rows) == [False, True]


async def test_error_event_marks_a_rate_limit_as_retryable(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    events = await _collect(
        _orchestrator(FakeProvider(fail_with=RateLimitedError("quota", provider="mock"))),
        session,
        _request(user_id),
    )
    error = events[-1]
    assert isinstance(error, ErrorEvent)
    assert error.retryable is True
    assert "quota" in error.message


class TestSpeechRendering:
    """``speech_text`` is what gets read aloud, so markdown must not survive."""

    def test_code_blocks_become_a_pointer_to_the_screen(self) -> None:
        spoken = to_speech("Try this:\n```python\nprint(1)\n```\nThat's it.")
        assert "print(1)" not in spoken
        assert "on screen" in spoken

    def test_markdown_markers_are_stripped(self) -> None:
        spoken = to_speech("## Heading\n- **first** item\n- `second`")
        assert "#" not in spoken and "*" not in spoken and "`" not in spoken
        assert "first item" in spoken

    def test_long_answers_are_truncated_at_a_sentence(self) -> None:
        spoken = to_speech(" ".join(["word"] * 200) + ". End.")
        assert len(spoken.split()) < 120
        assert spoken.endswith("The rest is on screen.")
