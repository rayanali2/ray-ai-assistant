"""Auth is one dependency, so it is worth testing exhaustively (ADR-0006)."""

from httpx import AsyncClient

from tests.conftest import TEST_TOKEN

PROTECTED = ["/dashboard", "/tasks", "/projects", "/agents", "/auth/user"]


async def test_health_is_public(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_health_reports_voice_capabilities(client: AsyncClient) -> None:
    # The frontend renders its voice controls from this rather than guessing.
    voice = (await client.get("/health")).json()["voice"]
    assert voice["wake_word_phrase"] == "Ray"
    assert voice["stt_backend"] in {"browser", "local"}


async def test_health_reports_actual_mock_provider(client: AsyncClient, monkeypatch) -> None:
    from ray.llm.registry import get_registry

    monkeypatch.setattr(get_registry(), "active_provider", "mock")
    health = (await client.get("/health")).json()
    assert health["llm_provider"] == "mock"
    assert "add a Gemini key" in health["diagnostics"]["suggestion"]


async def test_protected_routes_reject_missing_token(client: AsyncClient) -> None:
    for path in PROTECTED:
        assert (await client.get(path)).status_code == 401, path


async def test_protected_routes_reject_wrong_token(client: AsyncClient) -> None:
    client.headers["Authorization"] = "Bearer not-the-token"
    for path in PROTECTED:
        assert (await client.get(path)).status_code == 401, path


async def test_valid_token_resolves_the_seeded_user(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/auth/user")
    assert response.status_code == 200
    assert response.json()["name"] == "Test User"


async def test_token_is_not_a_prefix_match(client: AsyncClient) -> None:
    client.headers["Authorization"] = f"Bearer {TEST_TOKEN}-extra"
    assert (await client.get("/dashboard")).status_code == 401


async def test_update_current_user(auth_client: AsyncClient) -> None:
    response = await auth_client.patch(
        "/auth/user",
        json={"name": "Updated", "email": "updated@example.com", "preferences": {"theme": "dark"}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated"
    assert data["email"] == "updated@example.com"
    assert data["preferences"] == {"theme": "dark"}
