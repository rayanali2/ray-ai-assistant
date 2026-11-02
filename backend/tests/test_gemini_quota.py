"""Quota behavior without credentials, network calls or real-time sleeps."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from google.genai.errors import ClientError, ServerError

from ray.api.routes import health
from ray.config import Settings
from ray.llm.base import CompletionRequest, LLMMessage, ProviderUnavailableError, RateLimitedError
from ray.llm.providers import gemini
from ray.llm.quota import quota_delay
from ray.llm.registry import ProviderRegistry
from tests.fakes import FakeProvider

REQUEST = CompletionRequest(messages=[LLMMessage(role="user", content="Hello")])


def quota(message="PerDay quota exceeded. Please retry in 10h32m.", details=None):
    return ClientError(429, {"error": {"message": message, "details": details or []}})


@pytest.fixture
def scripted(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(gemini, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def make(scripts, fallback_models="lite"):
        calls = []

        async def generate(**kwargs):
            calls.append(kwargs["model"])
            events = scripts[kwargs["model"]].pop(0)

            async def stream():
                for event in events:
                    if isinstance(event, Exception):
                        raise event
                    yield SimpleNamespace(text=event, function_calls=None, usage_metadata=None)

            return stream()

        client = SimpleNamespace(
            aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=generate))
        )
        monkeypatch.setattr(gemini.genai, "Client", lambda **kwargs: client)
        provider = gemini.GeminiProvider(
            "fake-test-key", model="primary", fallback_models=fallback_models
        )
        return provider, calls, clock

    return make


@pytest.mark.parametrize(
    ("body", "seconds", "scope"),
    [
        (
            {"message": "PerDay Please retry in 10h32m3.5s", "details": [{"retryDelay": "32s"}]},
            37923.5,
            "daily",
        ),
        (
            {
                "message": "PerMinute",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12.5s"}
                ],
            },
            12.5,
            "per-minute",
        ),
        ({"details": [{"retryDelay": {"seconds": "3", "nanos": 500000000}}]}, 3.5, "rate"),
        ({"message": "Please retry in 1.25s"}, 1.25, "rate"),
        ({"details": [{"retryDelay": "invalid"}]}, 60, "rate"),
        ({"details": [{"retryDelay": {"seconds": "NaN"}}]}, 60, "rate"),
        ({}, 60, "rate"),
    ],
)
def test_quota_parsing(body, seconds, scope):
    assert quota_delay(body) == (seconds, scope)


def test_daily_without_delay_uses_next_pacific_midnight():
    assert quota_delay({"message": "PerDay"}, datetime(2026, 1, 1, 18, tzinfo=UTC)) == (
        14 * 3600,
        "daily",
    )


async def test_complete_tries_lite_and_skips_primary_until_reset(scripted):
    provider, calls, clock = scripted(
        {"primary": [[quota()], ["primary back"]], "lite": [["lite answer"], ["lite again"]]}
    )
    answer = await provider.complete(REQUEST)
    assert (answer.text, answer.model, answer.provider) == ("lite answer", "lite", "gemini")
    assert "daily quota" in provider.info().detail
    assert provider.cooldown_detail() == ""
    assert (await provider.complete(REQUEST)).text == "lite again"
    assert calls == ["primary", "lite", "lite"]
    clock[0] += 37921
    assert (await provider.complete(REQUEST)).text == "primary back"
    assert provider.info().detail == ""


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("fallback_models", ["", "lite"])
async def test_registry_skips_all_cooled_models_and_explains_mock(
    scripted, streaming, fallback_models
):
    provider, calls, clock = scripted(
        {"primary": [[quota()], ["real answer"]], "lite": [[quota("PerMinute retry in 60s")]]},
        fallback_models=fallback_models,
    )
    registry = ProviderRegistry(
        Settings(_env_file=None, llm_provider="gemini", llm_fallback_provider="mock")
    )
    registry.register("gemini", provider)
    degradations = []

    async def answer():
        if streaming:
            return "".join(
                [c.text async for c in registry.stream(REQUEST, on_degrade=degradations.append)]
            )
        return (await registry.complete(REQUEST, on_degrade=degradations.append)).text

    for _ in range(2):
        text = await answer()
        assert "Canned response" in text and "daily quota used up" in text
        assert registry.active_provider == registry.answering_provider == "mock"
    assert calls == (["primary", "lite"] if fallback_models else ["primary"])
    assert len(degradations) == 2
    assert "fake-test-key" not in json.dumps([i.detail for i in registry.describe()])
    clock[0] += 37921
    assert await answer() == "real answer"
    assert registry.active_provider == registry.answering_provider == "gemini"


async def test_stream_switches_models_before_output_but_never_midstream(scripted):
    provider, calls, _ = scripted(
        {"primary": [[quota()]], "lite": [["hello", quota("PerMinute retry in 3s")]]}
    )
    seen = []
    with pytest.raises(RateLimitedError):
        async for chunk in provider.stream(REQUEST):
            seen.append(chunk.text)
    assert seen == ["hello"]
    assert calls == ["primary", "lite"]
    assert "daily" in provider.cooldown_detail() and "per-minute" in provider.cooldown_detail()


async def test_stream_model_fallback_finishes_normally(scripted):
    provider, calls, _ = scripted({"primary": [[quota()]], "lite": [["hello"]]})
    chunks = [c async for c in provider.stream(REQUEST)]
    assert "".join(c.text for c in chunks) == "hello"
    assert chunks[-1].is_final
    assert calls == ["primary", "lite"]


async def test_nonquota_errors_do_not_try_model_fallback(scripted):
    provider, calls, _ = scripted(
        {"primary": [[ServerError(503, {"error": {"message": "offline"}})]]}
    )
    with pytest.raises(ProviderUnavailableError):
        await provider.complete(REQUEST)
    assert calls == ["primary"]
    assert provider.info().detail == ""


async def test_attribution_is_task_local_and_router_does_not_overwrite_it():
    registry = ProviderRegistry(
        Settings(
            _env_file=None,
            llm_provider="gemini",
            llm_router_provider="ollama",
            llm_fallback_provider="mock",
        )
    )
    registry.register("gemini", FakeProvider(name="gemini"))
    registry.register("ollama", FakeProvider(name="ollama"))

    async def one():
        await registry.complete(REQUEST)
        await registry.complete(REQUEST, role="router")
        await asyncio.sleep(0)
        assert registry.answering_provider == "gemini"

    async def two():
        await registry.complete(REQUEST, role="router")
        assert registry.answering_provider is None

    await asyncio.gather(one(), two())


async def test_health_reports_quota_not_missing_key(scripted, monkeypatch, auth_client):
    provider, _, _ = scripted({"primary": [[quota()]]}, fallback_models="")
    registry = ProviderRegistry(
        Settings(_env_file=None, llm_provider="gemini", llm_fallback_provider="mock")
    )
    registry.register("gemini", provider)
    await registry.complete(REQUEST)
    monkeypatch.setattr(health, "get_registry", lambda: registry)
    result = (await auth_client.get("/health")).json()
    assert result["llm_provider"] == "mock"
    assert "daily quota used up" in result["diagnostics"]["gemini_quota"]
    assert "No model configured" not in result["diagnostics"]["suggestion"]


async def test_healthy_primary_never_calls_lite(scripted):
    provider, calls, _ = scripted({"primary": [["healthy"]]})
    assert (await provider.complete(REQUEST)).text == "healthy"
    assert calls == ["primary"]
    assert provider.info().configured and provider.info().detail == ""
