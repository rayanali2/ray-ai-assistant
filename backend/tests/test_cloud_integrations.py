"""Google/Notion wire contracts and the actual approval/auth boundaries."""

import base64
import hashlib
import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest

from ray.agents.registry import AGENTS
from ray.config import Settings
from ray.domain.enums import IntegrationType, PermissionMode
from ray.integrations.calendar import GoogleCalendarAdapter
from ray.integrations.google_auth import GoogleAuthError, GoogleOAuth
from ray.integrations.knowledge import NotionAdapter
from ray.schemas import CalendarEventCreate, IntegrationCreate, IntegrationUpdate
from ray.services import calendar_service, integration_service, tool_service
from ray.tools.cloud_tools import CLOUD_TOOLS
from ray.tools.manager import ToolContext, ToolManager, get_manager


@pytest.fixture
def oauth(tmp_path):
    return GoogleOAuth(
        Settings(
            _env_file=None,
            data_dir=tmp_path,
            google_client_id="client",
            google_client_secret="client-secret",
        )
    )


def connected(oauth):
    oauth._save(
        {"access_token": "access", "refresh_token": "refresh", "expires_at": time.time() + 3600}
    )


async def test_google_pkce_state_exchange_and_private_storage(oauth):
    params = parse_qs(urlparse(oauth.auth_url("user")).query)
    assert params["scope"] == ["https://www.googleapis.com/auth/calendar.events"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    state = params["state"][0]

    def exchange(request):
        body = parse_qs(request.content.decode())
        assert body["code"] == ["authorization-code"]
        assert body["client_secret"] == ["client-secret"]
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(body["code_verifier"][0].encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert params["code_challenge"] == [expected]
        return httpx.Response(
            200, json={"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(exchange)) as client:
        oauth.client = client
        assert await oauth.callback("authorization-code", state) == "user"
        assert oauth.path.stat().st_mode & 0o777 == 0o600
        assert oauth.status() == "connected"
        assert await oauth.access_token() == "access"
        with pytest.raises(GoogleAuthError, match="state"):
            await oauth.callback("authorization-code", state)


async def test_google_missing_config_denial_expiry_and_missing_refresh(oauth, monkeypatch):
    monkeypatch.delenv("RAY_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("RAY_GOOGLE_CLIENT_SECRET", raising=False)
    empty = GoogleOAuth(Settings(_env_file=None, data_dir=oauth.path.parent))
    assert "not configured" in empty.status()
    with pytest.raises(GoogleAuthError, match="not configured"):
        empty.auth_url("u")
    assert "not connected" in oauth.status()
    with pytest.raises(GoogleAuthError, match="not connected"):
        await oauth.access_token()
    with pytest.raises(GoogleAuthError, match="state"):
        await oauth.callback("code", "forged")
    for code, expired in [("", False), ("code", True)]:
        state = parse_qs(urlparse(oauth.auth_url("u")).query)["state"][0]
        if expired:
            verifier, _, user = oauth.pending[state]
            oauth.pending[state] = (verifier, 0, user)
        with pytest.raises(GoogleAuthError):
            await oauth.callback(code, state)
    state = parse_qs(urlparse(oauth.auth_url("u")).query)["state"][0]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"access_token": "a"}))
    ) as client:
        oauth.client = client
        with pytest.raises(GoogleAuthError, match="refresh token"):
            await oauth.callback("code", state)
    assert not oauth.path.exists()


async def test_google_refresh_retains_refresh_token_and_revocation(oauth):
    connected(oauth)
    oauth._save({"refresh_token": "refresh", "expires_at": 0})

    def refresh(request):
        body = parse_qs(request.content.decode())
        assert body["grant_type"] == ["refresh_token"]
        assert body["refresh_token"] == ["refresh"]
        return httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})

    async with httpx.AsyncClient(transport=httpx.MockTransport(refresh)) as client:
        oauth.client = client
        assert await oauth.access_token() == "fresh"
        assert json.loads(oauth.path.read_text())["refresh_token"] == "refresh"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(400, json={"error": "invalid_grant"})
        )
    ) as client:
        oauth.client = client
        with pytest.raises(GoogleAuthError, match="revoked"):
            await oauth.access_token(force=True)
    assert not oauth.path.exists()


async def test_google_events_pagination_and_crud(oauth):
    connected(oauth)
    requests = []

    def wire(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer access"
        assert request.url.path.startswith("/calendar/v3/calendars/team@example.com/events")
        if request.method == "GET":
            assert request.url.params["timeMin"] == "2026-01-01T00:00:00Z"
            if "pageToken" not in request.url.params:
                return httpx.Response(
                    200, json={"items": [{"id": "first"}], "nextPageToken": "next"}
                )
            assert request.url.params["pageToken"] == "next"
            return httpx.Response(200, json={"items": [{"id": "second"}]})
        if request.method == "DELETE":
            return httpx.Response(204)
        assert json.loads(request.content)["summary"] == "Meeting"
        return httpx.Response(200, json={"id": "created"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as client:
        adapter = GoogleCalendarAdapter("team@example.com", oauth=oauth, client=client)
        result = await adapter.list_events("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        assert [item["id"] for item in result.data["events"]] == ["first", "second"]
        assert (await adapter.create_event({"summary": "Meeting"})).ok
        assert (await adapter.update_event("created", {"summary": "Meeting"})).ok
        assert (await adapter.delete_event("created")).ok
    assert [r.method for r in requests] == ["GET", "GET", "POST", "PATCH", "DELETE"]


@pytest.mark.parametrize("status", [403, 404, 429, 500])
async def test_google_empty_and_http_errors(oauth, status):
    connected(oauth)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(status, json={"error": "private-detail"})
        )
    ) as client:
        result = await GoogleCalendarAdapter(oauth=oauth, client=client).check()
    assert not result.ok
    assert "private-detail" not in result.error


async def test_google_retries_401_once_and_empty_list(oauth):
    connected(oauth)
    calls = []

    def wire(request):
        calls.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "fresh"})
        if request.headers["Authorization"] == "Bearer access":
            return httpx.Response(401)
        return httpx.Response(200, json={"items": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as client:
        oauth.client = client
        result = await GoogleCalendarAdapter(oauth=oauth, client=client).list_events("start", "end")
    assert result.ok and result.data == {"events": []}
    assert len(calls) == 3


async def test_notion_search_pagination_retry_after_and_headers(monkeypatch):
    sleeps, cursors = [], []

    async def pause(delay):
        sleeps.append(delay)

    monkeypatch.setattr("ray.integrations.knowledge.asyncio.sleep", pause)

    def wire(request):
        assert request.headers["Notion-Version"] == "2022-06-28"
        assert request.headers["Authorization"] == "Bearer secret"
        payload = json.loads(request.content)
        assert payload["filter"] == {"value": "database", "property": "object"}
        cursors.append(payload.get("start_cursor"))
        if len(cursors) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(
            200,
            json={
                "results": [{"id": str(len(cursors))}],
                "has_more": len(cursors) == 2,
                "next_cursor": "next",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as client:
        result = await NotionAdapter("secret", client=client).search("Ray", "database")
    assert result.ok and len(result.data["results"]) == 2
    assert sleeps == [2.0] and cursors == [None, None, "next"]


async def test_notion_recursive_paginated_markdown():
    def wire(request):
        if "/nested/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "type": "paragraph",
                            "paragraph": {"rich_text": [{"text": {"content": "Child"}}]},
                        }
                    ]
                },
            )
        if request.url.params.get("start_cursor"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "type": "to_do",
                            "to_do": {"checked": True, "rich_text": [{"plain_text": "Done"}]},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "nested",
                        "has_children": True,
                        "type": "heading_1",
                        "heading_1": {"rich_text": [{"plain_text": "Title"}]},
                    }
                ],
                "has_more": True,
                "next_cursor": "next",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as client:
        result = await NotionAdapter("secret", client=client).read_page("page")
    assert result.data["content"] == "# Title\nChild\n- [x] Done"


@pytest.mark.parametrize(
    "parent_type,title_property", [("page_id", "title"), ("database_id", "Project")]
)
async def test_notion_create_append_and_chunk_limits(parent_type, title_property):
    requests = []

    def wire(request):
        body = json.loads(request.content)
        requests.append((request.method, request.url.path, body))
        assert len(body["children"]) <= 100
        assert all(
            len(block["paragraph"]["rich_text"][0]["text"]["content"]) <= 2000
            for block in body["children"]
        )
        return httpx.Response(200, json={"id": "new-page"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as client:
        adapter = NotionAdapter("secret", client=client)
        assert (
            await adapter.create_page("parent", "Title", "x" * 202000, parent_type, title_property)
        ).ok
        assert (await adapter.append_page("new-page", "extra")).ok
    assert requests[0][2]["parent"] == {parent_type: "parent"}
    assert title_property in requests[0][2]["properties"]
    assert [r[0] for r in requests] == ["POST", "PATCH", "PATCH"]


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
async def test_notion_error_and_rate_limit_exhaustion(status, monkeypatch):
    async def pause(delay):
        pass

    monkeypatch.setattr("ray.integrations.knowledge.asyncio.sleep", pause)
    calls = []

    def wire(request):
        calls.append(request)
        return httpx.Response(status, json={"message": "secret"}, headers={"Retry-After": "0"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as client:
        result = await NotionAdapter("secret", client=client).check()
    assert not result.ok and "secret" not in result.error
    assert len(calls) == (3 if status == 429 else 1)


async def test_notion_missing_token_empty_pages_and_network(monkeypatch):
    monkeypatch.setattr(
        "ray.integrations.knowledge.get_settings", lambda: Settings(_env_file=None, notion_token="")
    )
    assert "RAY_NOTION_TOKEN" in (await NotionAdapter().check()).error
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"results": [], "has_more": False})
        )
    ) as client:
        adapter = NotionAdapter("secret", client=client)
        assert (await adapter.search()).data == {"results": []}
        assert (await adapter.read_page("page")).data == {"content": ""}

    def offline(request):
        raise httpx.ConnectError("offline")

    async with httpx.AsyncClient(transport=httpx.MockTransport(offline)) as client:
        assert not (await NotionAdapter("secret", client=client).check()).ok


async def test_google_callback_boundary_and_connection_registration(
    oauth, monkeypatch, auth_client, client, user
):
    monkeypatch.setattr("ray.api.routes.integrations.get_google_oauth", lambda: oauth)
    response = await auth_client.get("/integrations/google/auth-url")
    assert response.status_code == 200
    params = parse_qs(urlparse(response.json()["url"]).query)
    client.headers.clear()
    assert (await client.get("/integrations/google/auth-url")).status_code == 401
    assert (
        await client.get("/integrations/google/callback?code=code&state=forged")
    ).status_code == 400
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"access_token": "a", "refresh_token": "r"})
        )
    ) as wire:
        oauth.client = wire
        url = "/integrations/google/callback?" + urlencode(
            {"code": "code", "state": params["state"][0]}
        )
        callback = await client.get(url)
        assert callback.status_code == 200
        assert "refresh_token" not in callback.text
        assert (await client.get(url)).status_code == 400
    client.headers["Authorization"] = "Bearer test-token"
    integrations = (await client.get("/integrations")).json()
    assert integrations[0]["provider"] == "google"
    assert integrations[0]["status"] == "connected"


@pytest.mark.parametrize(
    "tool", [tool for tool in CLOUD_TOOLS if tool.side_effect], ids=lambda tool: tool.name
)
async def test_cloud_writes_need_approval_even_with_standing_allow(
    tool, session, user, monkeypatch
):
    calls = []

    async def handler(ctx, arguments):
        calls.append(arguments)
        return {"written": True}

    tool = replace(tool, handler=handler)
    manager = ToolManager()
    manager.register(tool)
    await tool_service.set_permission(session, user.id, tool.name, PermissionMode.ALWAYS_ALLOW)
    result = await manager.invoke(
        ToolContext(session=session, user_id=user.id), tool.name, {"title": "Approved content"}
    )
    assert result.status == "pending_approval" and calls == []
    approved = await manager.execute_approved(session, user.id, result.invocation_id)
    assert approved.status == "executed" and calls == [{"title": "Approved content"}]


async def test_dashboard_merges_google_and_local_and_survives_failure(
    oauth, monkeypatch, session, user
):
    connected(oauth)
    monkeypatch.setattr("ray.services.calendar_service.get_google_oauth", lambda: oauth)
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    await calendar_service.create_event(
        session,
        user.id,
        CalendarEventCreate(title="Local", start_time=today, end_time=today + timedelta(hours=1)),
    )

    def wire(request):
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "remote",
                        "summary": "Google all-day",
                        "start": {"date": today.date().isoformat()},
                        "end": {"date": (today + timedelta(days=1)).date().isoformat()},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as client:
        adapter = GoogleCalendarAdapter(oauth=oauth, client=client)

        async def resolve(*args, **kwargs):
            return adapter

        monkeypatch.setattr(integration_service, "resolve_adapter", resolve)
        events = await calendar_service.dashboard_events(
            session, user.id, today, today + timedelta(days=1)
        )
        assert {e.title for e in events} == {"Local", "Google all-day"}
        remote = next(e for e in events if e.source == "google")
        assert remote.external_id == "remote" and remote.end_time - remote.start_time == timedelta(
            days=1
        )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    ) as client:
        adapter.client = client
        assert (
            len(
                await calendar_service.dashboard_events(
                    session, user.id, today, today + timedelta(days=1)
                )
            )
            == 1
        )


async def test_disabled_cloud_integration_does_not_use_environment_fallback(session, user):
    await integration_service.create_integration(
        session,
        user.id,
        IntegrationCreate(type=IntegrationType.CALENDAR, provider="google", enabled=False),
    )
    adapter = await integration_service.resolve_adapter(
        session,
        user.id,
        IntegrationType.CALENDAR,
        "google",
        fallback=integration_service.IntegrationAdapterConfig(
            type=IntegrationType.CALENDAR, provider="google"
        ),
    )
    assert adapter is None


async def test_google_failed_reconnect_preserves_existing_credentials(oauth):
    connected(oauth)
    state = parse_qs(urlparse(oauth.auth_url("u")).query)["state"][0]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(400, json={"error": "invalid_grant"})
        )
    ) as client:
        oauth.client = client
        with pytest.raises(GoogleAuthError):
            await oauth.callback("expired-code", state)
    assert oauth.status() == "connected"


@pytest.mark.parametrize("body", [[], {"error": "invalid_client"}])
async def test_google_token_exchange_error_is_safe(oauth, body):
    state = parse_qs(urlparse(oauth.auth_url("u")).query)["state"][0]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(400, json=body))
    ) as client:
        oauth.client = client
        with pytest.raises(GoogleAuthError) as error:
            await oauth.callback("code", state)
        assert "client-secret" not in str(error.value)


async def test_google_storage_failure_is_actionable(oauth, monkeypatch):
    state = parse_qs(urlparse(oauth.auth_url("u")).query)["state"][0]

    def no_disk(data):
        raise PermissionError("private filesystem detail")

    monkeypatch.setattr(oauth, "_save", no_disk)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"access_token": "a", "refresh_token": "r"})
        )
    ) as client:
        oauth.client = client
        with pytest.raises(GoogleAuthError, match="RAY_DATA_DIR"):
            await oauth.callback("code", state)


async def test_notion_partial_create_reports_existing_page():
    calls = []

    def wire(request):
        calls.append(request)
        return (
            httpx.Response(200, json={"id": "existing-page"})
            if request.method == "POST"
            else httpx.Response(500)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as client:
        result = await NotionAdapter("secret", client=client).create_page(
            "parent", "Title", "x" * 202000
        )
    assert not result.ok and "was created" in result.error and "existing-page" in result.error
    assert len(calls) == 2


async def test_cloud_tool_dispatch_and_read_validation(oauth, monkeypatch, session, user):
    connected(oauth)
    requests = []

    def wire(request):
        requests.append(request)
        if request.url.host == "api.notion.com":
            if request.url.path.endswith("/search") or request.method == "GET":
                return httpx.Response(200, json={"results": [], "has_more": False})
            return httpx.Response(200, json={"id": "created-page"})
        return httpx.Response(200, json={"items": [], "id": "event"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as client:

        async def resolve(session, user_id, kind, provider, **kwargs):
            return (
                GoogleCalendarAdapter(oauth=oauth, client=client)
                if provider == "google"
                else NotionAdapter("secret", client=client)
            )

        monkeypatch.setattr(integration_service, "resolve_adapter", resolve)
        ctx = ToolContext(session=session, user_id=user.id)
        manager = get_manager()
        payloads = {
            "google_calendar.list": {
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-01-02T00:00:00Z",
            },
            "google_calendar.create": {"event": {"summary": "Test"}},
            "google_calendar.update": {"event_id": "event", "event": {"summary": "Changed"}},
            "google_calendar.delete": {"event_id": "event"},
            "notion.search": {},
            "notion.read": {"page_id": "page"},
            "notion.create": {"parent_id": "parent", "title": "Test"},
            "notion.append": {"page_id": "page", "content": "Text"},
        }
        for tool in CLOUD_TOOLS:
            agent = AGENTS["planning" if tool.name.startswith("google") else "research"]
            before = len(requests)
            result = await manager.invoke(ctx, tool.name, payloads[tool.name], allowed=agent.tools)
            if tool.side_effect:
                assert result.status == "pending_approval" and len(requests) == before
                result = await manager.execute_approved(session, user.id, result.invocation_id)
            assert result.status == "executed", result.error
            assert len(requests) == before + 1
        invalid = await manager.invoke(ctx, "google_calendar.list", {})
        assert invalid.status == "failed" and "start is required" in invalid.error
        invalid = await manager.invoke(
            ctx, "google_calendar.list", {"start": "2026-01-02", "end": "2026-01-01"}
        )
        assert invalid.status == "failed" and "RFC3339" in invalid.error


async def test_cloud_connection_status_and_health_count(
    oauth, monkeypatch, auth_client, session, user
):
    connected(oauth)
    monkeypatch.setattr(integration_service, "get_google_oauth", lambda: oauth)
    monkeypatch.setattr(
        integration_service,
        "get_settings",
        lambda: Settings(_env_file=None, notion_token="private-token"),
    )
    health = (await auth_client.get("/health")).json()
    assert health["diagnostics"]["integrations"] == "2 configured"
    assert health["diagnostics"]["google"] == "connected"
    assert "private-token" not in json.dumps(health)
    row = await integration_service.create_integration(
        session,
        user.id,
        IntegrationCreate(
            type=IntegrationType.KNOWLEDGE,
            provider="notion",
            credentials_reference="env:CUSTOM_NOTION",
            enabled=False,
        ),
    )
    await session.commit()
    statuses = (await auth_client.get("/integrations/connections")).json()
    assert statuses["notion"] == "disabled in Settings"
    await integration_service.update_integration(
        session, user.id, row.id, IntegrationUpdate(enabled=True)
    )
    await session.commit()
    statuses = (await auth_client.get("/integrations/connections")).json()
    assert "credentials reference configured" in statuses["notion"]
    health = (await auth_client.get("/health")).json()
    assert health["diagnostics"]["integrations"] == "2 configured"
    assert "private-token" not in json.dumps(statuses)


async def test_reenabled_cloud_integration_resolves(session, user):
    row = await integration_service.create_integration(
        session,
        user.id,
        IntegrationCreate(type=IntegrationType.CALENDAR, provider="google", enabled=False),
    )
    await integration_service.update_integration(
        session, user.id, row.id, IntegrationUpdate(enabled=True)
    )
    assert isinstance(
        await integration_service.resolve_adapter(
            session, user.id, IntegrationType.CALENDAR, "google"
        ),
        GoogleCalendarAdapter,
    )
