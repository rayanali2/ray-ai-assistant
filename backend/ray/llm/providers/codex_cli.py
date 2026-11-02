"""Codex exec JSONL adapter; only completed agent messages are user-visible."""

from ray.llm.base import CompletionRequest
from ray.llm.providers.cli import CLIProvider


class CodexCLIProvider(CLIProvider):
    name = "codex_cli"
    login_command = "codex login"

    def __init__(
        self, *, binary: str = "codex", model: str = "", timeout_seconds: float = 120
    ) -> None:
        super().__init__(binary=binary, model=model, timeout_seconds=timeout_seconds)

    def arguments(self, request: CompletionRequest) -> list[str]:
        args = [
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "-",
        ]
        if self.model:
            args += ["--model", self.model]
        return args

    def text(self, event: dict[str, object], emitted: bool) -> str:
        if event.get("type") == "item.completed":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                return text if isinstance(text, str) else ""
        return ""
