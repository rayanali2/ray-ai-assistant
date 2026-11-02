"""Isolated, bounded subprocess transport for subscription CLI adapters."""

import asyncio
import contextlib
import json
import os
import shutil
import signal
from abc import abstractmethod
from collections.abc import AsyncIterator
from tempfile import TemporaryDirectory

from ray.llm.base import (
    Chunk,
    Completion,
    CompletionRequest,
    LLMProvider,
    ProviderInfo,
    ProviderUnavailableError,
)


class CLIProvider(LLMProvider):
    login_command = ""

    def __init__(self, *, binary: str, model: str = "", timeout_seconds: float = 120) -> None:
        self.binary = binary
        self.model = model
        self.timeout_seconds = timeout_seconds

    def info(self) -> ProviderInfo:
        found = shutil.which(self.binary) is not None
        return ProviderInfo(
            name=self.name,
            model=self.model or "CLI default",
            configured=found,
            detail="" if found else f"Install {self.binary}; run {self.login_command}",
        )

    def executable(self) -> str | None:
        binary = shutil.which(self.binary)
        return os.path.abspath(binary) if binary else None

    def unavailable(self, reason: str) -> ProviderUnavailableError:
        return ProviderUnavailableError(
            f"{self.name}: {reason}. Sign in with `{self.login_command}` and retry.",
            provider=self.name,
        )

    @abstractmethod
    def arguments(self, request: CompletionRequest) -> list[str]: ...

    @abstractmethod
    def text(self, event: dict[str, object], emitted: bool) -> str: ...

    async def complete(self, request: CompletionRequest) -> Completion:
        parts = [chunk.text async for chunk in self.stream(request)]
        return Completion(
            text="".join(parts), provider=self.name, model=self.model or "CLI default"
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[Chunk]:
        binary = await asyncio.to_thread(self.executable)
        if binary is None:
            raise self.unavailable("executable not found")
        prompt = "\n\n".join(
            [f"system: {request.system}"]
            + [f"{message.role}: {message.content}" for message in request.messages]
        )
        proc: asyncio.subprocess.Process | None = None
        stderr_task: asyncio.Task[None] | None = None
        # Never include raw CLI diagnostics: they can contain credentials or prompts.
        auth_failed = False

        async def drain(reader: asyncio.StreamReader) -> None:
            nonlocal auth_failed
            tail = ""
            while data := await reader.read(4096):
                tail = (tail + data.decode(errors="replace").lower())[-8192:]
                if any(
                    marker in tail
                    for marker in (
                        "not logged in",
                        "not authenticated",
                        "authentication",
                        "please log in",
                    )
                ):
                    auth_failed = True

        with TemporaryDirectory(prefix="ray-chat-") as cwd:
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    proc = await asyncio.create_subprocess_exec(
                        binary,
                        *self.arguments(request),
                        cwd=cwd,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        start_new_session=os.name == "posix",
                        limit=4 * 1024 * 1024,
                    )
                    assert proc.stdin is not None and proc.stdout is not None
                    assert proc.stderr is not None
                    stderr_task = asyncio.create_task(drain(proc.stderr))
                    proc.stdin.write(prompt.encode())
                    await proc.stdin.drain()
                    proc.stdin.close()
                    emitted = False
                    async for line in proc.stdout:
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                        except (ValueError, UnicodeError) as exc:
                            raise self.unavailable(
                                "invalid JSON output (check CLI login/version)"
                            ) from exc
                        if not isinstance(event, dict):
                            raise self.unavailable("invalid event")
                        if (
                            event.get("is_error")
                            or event.get("type") in {"error", "turn.failed"}
                            or event.get("error")
                        ):
                            raise self.unavailable("CLI reported an error")
                        text = self.text(event, emitted)
                        if any(
                            marker in text.lower()
                            for marker in (
                                "not logged in",
                                "please log in",
                                "not authenticated",
                            )
                        ):
                            raise self.unavailable("CLI is not logged in")
                        if text:
                            emitted = True
                            yield Chunk(text=text)
                    code = await proc.wait()
                    await stderr_task
                    if code or auth_failed or not emitted:
                        raise self.unavailable(
                            f"CLI exited {code} or returned no authenticated reply"
                        )
                    yield Chunk(is_final=True)
            except (TimeoutError, OSError, ValueError) as exc:
                raise self.unavailable("CLI timed out or could not run") from exc
            finally:
                if proc is not None and proc.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        if os.name == "posix":
                            os.killpg(proc.pid, signal.SIGKILL)
                        else:
                            proc.kill()
                    await proc.wait()
                if stderr_task is not None:
                    stderr_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await stderr_task
