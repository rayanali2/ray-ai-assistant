"""The only interface the rest of Ray knows about a model (ADR-0001).

Nothing outside ``ray/llm/`` may import a vendor SDK, so adding a provider later is
a new file here and an environment variable — never a change to an agent.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class LLMMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class ToolSpec:
    """A tool as the *model* sees it (ADR-0010).

    Deliberately not the tool itself: no callable, no credentials, nothing that could
    be invoked from here. ``parameters`` is JSON Schema, which is the one description
    format every provider's function calling accepts.
    """

    name: str
    description: str
    parameters: dict[str, object]


@dataclass(frozen=True)
class ToolCall:
    """A tool the model asked for. Whether it *runs* is not the model's decision
    (ADR-0014) — that is the Tool Manager's."""

    name: str
    arguments: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletionRequest:
    """A provider-neutral request.

    ``system`` is separate from ``messages`` because providers disagree about where
    system instructions belong; each adapter places it correctly.
    """

    messages: Sequence[LLMMessage]
    system: str = ""
    temperature: float = 0.7
    max_output_tokens: int | None = None
    tools: Sequence[ToolSpec] = ()
    """Offered, never required: a provider without function calling ignores these and
    the caller falls back to something deterministic (ADR-0017)."""


@dataclass(frozen=True)
class Chunk:
    """One streamed fragment. ``text`` may be empty on the final bookkeeping chunk."""

    text: str = ""
    is_final: bool = False


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    # Populated only when the request offered tools and the model asked for one.
    tool_calls: tuple[ToolCall, ...] = ()
    # None when the provider does not report usage; not every free tier does.
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMError(Exception):
    """Base class for provider failures.

    The distinction that matters to the orchestrator is whether trying a different
    provider could help, which is what ``is_retryable`` answers.
    """

    is_retryable = False

    def __init__(self, message: str, *, provider: str = "") -> None:
        super().__init__(message)
        self.provider = provider


class ProviderUnavailableError(LLMError):
    """The provider is not configured, not reachable, or down."""

    is_retryable = True


class RateLimitedError(LLMError):
    """A free tier said no. Trying the fallback is exactly the right response."""

    is_retryable = True


class ProviderRequestError(LLMError):
    """The request itself was rejected. Retrying elsewhere would fail the same way."""

    is_retryable = False


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    model: str
    configured: bool
    # Populated when ``configured`` is False, so /health can say *why*.
    detail: str = ""


class LLMProvider(ABC):
    """Implemented once per vendor."""

    name: str = "unknown"

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> Completion:
        """Return the whole answer. Used for short internal calls, not chat."""

    @abstractmethod
    def stream(self, request: CompletionRequest) -> AsyncIterator[Chunk]:
        """Yield the answer as it is produced."""

    @abstractmethod
    def info(self) -> ProviderInfo:
        """Describe this provider without calling it."""

    def supports_tools(self) -> bool:
        """Whether the adapter can carry tool definitions (Phase 4 uses this)."""
        return False

    def cooldown_detail(self) -> str:
        """Nonempty while every model is cooling down; the registry must skip it."""
        return ""

    async def aclose(self) -> None:
        """Release any client resources. Overridden where there is a connection."""
        return None


@dataclass
class StreamAccumulator:
    """Collects a stream into a final answer.

    Shared by every caller that needs both the live tokens and the complete text,
    so the two can never disagree.
    """

    parts: list[str] = field(default_factory=list)

    def add(self, chunk: Chunk) -> None:
        if chunk.text:
            self.parts.append(chunk.text)

    @property
    def text(self) -> str:
        return "".join(self.parts)
