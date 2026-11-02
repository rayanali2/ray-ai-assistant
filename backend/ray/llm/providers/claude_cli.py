"""Claude Code print-mode stream-json adapter."""

from ray.llm.base import CompletionRequest
from ray.llm.providers.cli import CLIProvider


class ClaudeCLIProvider(CLIProvider):
    name = "claude_cli"
    login_command = "claude"

    def __init__(
        self, *, binary: str = "claude", model: str = "", timeout_seconds: float = 120
    ) -> None:
        super().__init__(binary=binary, model=model, timeout_seconds=timeout_seconds)

    def arguments(self, request: CompletionRequest) -> list[str]:
        args = [
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--tools",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--setting-sources",
            "",
            "--settings",
            '{"disableAllHooks":true}',
            "--disable-slash-commands",
            "--no-session-persistence",
            "--system-prompt",
            request.system or "You are Ray.",
        ]
        if self.model:
            args += ["--model", self.model]
        return args

    def text(self, event: dict[str, object], emitted: bool) -> str:
        if event.get("type") == "stream_event":
            inner = event.get("event")
            if isinstance(inner, dict) and inner.get("type") == "content_block_delta":
                delta = inner.get("delta")
                if isinstance(delta, dict) and delta.get("type") == "text_delta":
                    value = delta.get("text")
                    return value if isinstance(value, str) else ""
        if event.get("type") == "result" and not emitted:
            result = event.get("result")
            return result if isinstance(result, str) else ""
        return ""
