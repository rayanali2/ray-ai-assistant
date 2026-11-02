"""Resolves a role to a provider, and degrades instead of failing (ADR-0001).

Two ideas live here:

* **Roles, not one global provider.** ``agent`` answers, ``router`` classifies. They
  have different latency and quality needs, so they may be different models.
* **A chain, not a single choice.** A provider that is unconfigured, rate limited, or
  down hands off to the next one, and the degradation is recorded so the UI can say
  so rather than silently producing a worse answer.
"""

from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal, cast

import structlog

from ray.config import ProviderName, Settings, get_settings
from ray.llm.base import (
    Chunk,
    Completion,
    CompletionRequest,
    LLMError,
    LLMProvider,
    ProviderInfo,
    ProviderUnavailableError,
)
from ray.llm.providers.mock import MockProvider

log = structlog.get_logger()

Role = Literal["agent", "router"]


@dataclass(frozen=True)
class Degradation:
    """Recorded when a provider fails and the next one is tried."""

    failed_provider: str
    reason: str


def _build(name: ProviderName, settings: Settings) -> LLMProvider:
    """Construct one provider. Imports are local so an unused SDK is never loaded."""
    if name == "claude_cli":
        from ray.llm.providers.claude_cli import ClaudeCLIProvider

        return ClaudeCLIProvider(
            binary=settings.claude_cli_binary,
            model=settings.claude_cli_model,
            timeout_seconds=settings.cli_timeout_seconds,
        )
    if name == "codex_cli":
        from ray.llm.providers.codex_cli import CodexCLIProvider

        return CodexCLIProvider(
            binary=settings.codex_cli_binary,
            model=settings.codex_cli_model,
            timeout_seconds=settings.cli_timeout_seconds,
        )
    if name == "gemini":
        if not settings.gemini_api_key:
            raise ProviderUnavailableError("RAY_GEMINI_API_KEY is not set", provider="gemini")
        from ray.llm.providers.gemini import GeminiProvider

        return GeminiProvider(
            settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_ms=settings.gemini_timeout_ms,
            retry_attempts=settings.gemini_retry_attempts,
            fallback_models=settings.gemini_fallback_models,
        )
    if name == "ollama":
        from ray.llm.providers.ollama import OllamaProvider

        return OllamaProvider(host=settings.ollama_host, model=settings.ollama_model)
    return MockProvider(delay_seconds=settings.mock_stream_delay_seconds)


class ProviderRegistry:
    """Owns provider instances for the lifetime of the process.

    Providers are built lazily and cached: constructing a client is cheap, but doing
    it per request would leak connection pools.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._instances: dict[str, LLMProvider] = {}
        self._unavailable: dict[str, str] = {}
        self.active_provider: str | None = None
        self._answering_provider: ContextVar[str | None] = ContextVar(
            "answering_provider", default=None
        )

    @property
    def answering_provider(self) -> str | None:
        """Last agent answer in this request/task, unlike the process-wide health field."""
        return self._answering_provider.get()

    def quota_notice(self) -> str:
        provider = self._instances.get("gemini")
        return provider.info().detail if provider is not None else ""

    def _mock_notice(self, provider: LLMProvider) -> str:
        quota = self.quota_notice() if provider.name == "mock" else ""
        return f"[Canned response — {quota}. No live provider answered.]\n\n" if quota else ""

    # -- chain construction -------------------------------------------------

    def chain(self, role: Role = "agent") -> tuple[ProviderName, ...]:
        """Preferred provider first, then the fallbacks, deduplicated.

        ``mock`` is always last so Ray answers even when nothing is configured.
        """
        settings = self._settings
        preferred = settings.llm_router_provider if role == "router" else None
        ordered = [
            preferred or settings.llm_provider,
            *(
                cast(ProviderName, name.strip())
                for name in (settings.llm_fallback_provider or "").split(",")
                if name.strip()
            ),
        ]
        seen: list[ProviderName] = []
        for name in ordered:
            if name != "mock" and name not in seen:
                seen.append(name)
        seen.append("mock")
        return tuple(seen)

    def register(self, name: ProviderName, provider: LLMProvider) -> None:
        """Install a provider instance directly.

        The seam that lets tests run the whole pipeline against a scripted model,
        and lets a future provider be injected without touching construction.
        """
        self._instances[name] = provider

    def get(self, name: ProviderName) -> LLMProvider:
        cached = self._instances.get(name)
        if cached is not None:
            return cached
        provider = _build(name, self._settings)
        self._instances[name] = provider
        return provider

    def _available(
        self,
        chain: Sequence[ProviderName],
        on_degrade: Callable[[Degradation], None] | None = None,
    ) -> Iterator[LLMProvider]:
        for name in chain:
            try:
                provider = self.get(name)
                cooldown = provider.cooldown_detail()
                if cooldown:
                    if on_degrade is not None:
                        on_degrade(Degradation(failed_provider=name, reason=cooldown))
                    continue
                yield provider
            except LLMError as exc:
                # Unconfigured is normal, not exceptional: no key means skip.
                self._unavailable[name] = str(exc)
                log.info("llm.provider_skipped", provider=name, reason=str(exc))

    # -- calling ------------------------------------------------------------

    async def complete(
        self,
        request: CompletionRequest,
        *,
        role: Role = "agent",
        on_degrade: Callable[[Degradation], None] | None = None,
    ) -> Completion:
        last: LLMError | None = None
        for provider in self._available(self.chain(role), on_degrade):
            try:
                completion = await provider.complete(request)
                if role == "agent":
                    completion.text = self._mock_notice(provider) + completion.text
                    self.active_provider = completion.provider
                    self._answering_provider.set(completion.provider)
                return completion
            except LLMError as exc:
                last = self._handle(exc, provider, on_degrade)
                if not exc.is_retryable:
                    raise
        raise last or ProviderUnavailableError("No provider is available")

    async def stream(
        self,
        request: CompletionRequest,
        *,
        role: Role = "agent",
        on_degrade: Callable[[Degradation], None] | None = None,
    ) -> AsyncIterator[Chunk]:
        """Stream from the first provider that works.

        Falling back mid-stream is deliberately not attempted: the user has already
        seen tokens, and restarting would duplicate them. Only a failure *before*
        the first chunk moves to the next provider.
        """
        last: LLMError | None = None
        for provider in self._available(self.chain(role), on_degrade):
            started = False
            try:
                async for chunk in provider.stream(request):
                    if role == "agent" and not started:
                        notice = self._mock_notice(provider)
                        if notice:
                            yield Chunk(text=notice)
                    started = True
                    if role == "agent":
                        self.active_provider = provider.name
                        self._answering_provider.set(provider.name)
                    yield chunk
                return
            except LLMError as exc:
                if started or not exc.is_retryable:
                    raise
                last = self._handle(exc, provider, on_degrade)
        raise last or ProviderUnavailableError("No provider is available")

    def _handle(
        self,
        exc: LLMError,
        provider: LLMProvider,
        on_degrade: Callable[[Degradation], None] | None,
    ) -> LLMError:
        log.warning("llm.provider_failed", provider=provider.name, error=str(exc))
        if on_degrade is not None and exc.is_retryable:
            on_degrade(Degradation(failed_provider=provider.name, reason=str(exc)))
        return exc

    # -- introspection ------------------------------------------------------

    def describe(self, role: Role = "agent") -> list[ProviderInfo]:
        """What /health reports: the chain, and why anything in it is unusable."""
        described: list[ProviderInfo] = []
        for name in self.chain(role):
            try:
                described.append(self.get(name).info())
            except LLMError as exc:
                described.append(
                    ProviderInfo(name=name, model="", configured=False, detail=str(exc))
                )
        return described

    async def aclose(self) -> None:
        for provider in self._instances.values():
            await provider.aclose()
        self._instances.clear()


_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry


async def dispose_registry() -> None:
    global _registry
    if _registry is not None:
        await _registry.aclose()
        _registry = None
