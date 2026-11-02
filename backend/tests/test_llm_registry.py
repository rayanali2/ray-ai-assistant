"""Provider selection and degradation (ADR-0001)."""

import json
from dataclasses import asdict

import pytest

from ray.config import Settings
from ray.llm.base import (
    CompletionRequest,
    LLMMessage,
    ProviderRequestError,
    ProviderUnavailableError,
    RateLimitedError,
    StreamAccumulator,
)
from ray.llm.providers.mock import MockProvider
from ray.llm.registry import Degradation, ProviderRegistry
from tests.fakes import FakeProvider

REQUEST = CompletionRequest(messages=[LLMMessage(role="user", content="hi")])


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "llm_provider": "gemini",
        "llm_fallback_provider": "ollama",
        "gemini_api_key": "",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_chain_always_ends_in_mock() -> None:
    # Ray must be able to answer with nothing configured at all.
    registry = ProviderRegistry(_settings())
    assert registry.chain() == ("gemini", "ollama", "mock")
    assert registry.chain()[-1] == "mock"


def test_chain_deduplicates_and_honours_router_role() -> None:
    registry = ProviderRegistry(
        _settings(llm_provider="mock", llm_fallback_provider="mock", llm_router_provider="ollama")
    )
    assert registry.chain("agent") == ("mock",)
    assert registry.chain("router") == ("ollama", "mock")


async def test_unconfigured_gemini_is_skipped_not_fatal() -> None:
    """A missing API key is a configuration state, not an error."""
    registry = ProviderRegistry(_settings(llm_provider="gemini", llm_fallback_provider="mock"))
    completion = await registry.complete(REQUEST)
    assert completion.provider == "mock"


async def test_active_provider_tracks_answers_not_router() -> None:
    registry = ProviderRegistry(_settings(llm_provider="gemini", llm_fallback_provider="mock"))
    assert registry.active_provider is None
    await registry.complete(REQUEST, role="router")
    assert registry.active_provider is None
    await registry.complete(REQUEST)
    assert registry.active_provider == "mock"
    registry.active_provider = None
    async for _ in registry.stream(REQUEST):
        assert registry.active_provider == "mock"


async def test_rate_limited_provider_falls_back_and_reports_degradation() -> None:
    registry = ProviderRegistry(
        _settings(llm_provider="gemini", llm_fallback_provider="mock", gemini_api_key="set")
    )
    failing = FakeProvider(name="gemini", fail_with=RateLimitedError("quota", provider="gemini"))
    registry.register("gemini", failing)
    registry.register("mock", MockProvider())

    degradations: list[Degradation] = []
    accumulator = StreamAccumulator()
    async for chunk in registry.stream(REQUEST, on_degrade=degradations.append):
        accumulator.add(chunk)

    assert "mock provider" in accumulator.text
    assert [d.failed_provider for d in degradations] == ["gemini"]


async def test_non_retryable_error_is_not_retried_elsewhere() -> None:
    """A malformed request would fail identically on the fallback."""
    registry = ProviderRegistry(_settings(llm_provider="mock"))
    registry.register(
        "mock",
        FakeProvider(name="mock", fail_with=ProviderRequestError("bad request", provider="mock")),
    )
    with pytest.raises(ProviderRequestError):
        await registry.complete(REQUEST)


async def test_failure_after_first_chunk_is_not_retried() -> None:
    """Restarting mid-stream would duplicate tokens the user has already read."""
    registry = ProviderRegistry(_settings(llm_provider="mock"))
    registry.register(
        "mock",
        FakeProvider(
            ["one", "two", "three"],
            name="mock",
            fail_with=ProviderUnavailableError("died", provider="mock"),
            fail_after_chunks=2,
        ),
    )

    seen: list[str] = []
    with pytest.raises(ProviderUnavailableError):
        async for chunk in registry.stream(REQUEST):
            seen.append(chunk.text)
    assert seen == ["one", "two"]


def test_describe_explains_why_a_provider_is_unusable() -> None:
    registry = ProviderRegistry(_settings(llm_provider="gemini", gemini_api_key=""))
    described = {info.name: info for info in registry.describe()}
    assert described["gemini"].configured is False
    assert "RAY_GEMINI_API_KEY" in described["gemini"].detail
    assert described["mock"].configured is True


async def test_mock_provider_streams_in_fragments() -> None:
    """Consumers must exercise accumulation, not receive one big chunk."""
    provider = MockProvider()
    chunks = [chunk async for chunk in provider.stream(REQUEST)]
    assert len([c for c in chunks if c.text]) > 1
    assert chunks[-1].is_final
    assert "hi" in "".join(c.text for c in chunks)


async def test_describe_never_returns_the_credential() -> None:
    """A leaked key would leak to the browser: `/chat/providers` is client-visible."""
    sentinel = "sk-do-not-leak-me"
    registry = ProviderRegistry(_settings(gemini_api_key=sentinel))

    blob = json.dumps([asdict(info) for info in registry.describe()])

    assert sentinel not in blob
    assert "gemini" in blob
