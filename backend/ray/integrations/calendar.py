"""Local calendar/ICS and optional live Google Calendar access."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from ray.integrations.base import Adapter, AdapterResult
from ray.integrations.google_auth import GoogleAuthError, GoogleOAuth, get_google_oauth


class LocalCalendarAdapter(Adapter):
    """Local calendar: the database is the source of truth."""

    name = "local_calendar"

    async def check(self) -> AdapterResult:
        return AdapterResult(ok=True, data={}, error="")

    async def read(self, path: str = "", **kwargs: Any) -> AdapterResult:
        return AdapterResult(ok=True, data={"note": "Use calendar.list and calendar.create tools."})


class GoogleCalendarAdapter(Adapter):
    """Google Calendar events on the primary or configured calendar."""

    name = "google_calendar"

    def __init__(
        self,
        calendar_id: str = "primary",
        *,
        oauth: GoogleOAuth | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.calendar_id = calendar_id
        self.oauth = oauth or get_google_oauth()
        self.client = client

    async def _api(self, method: str, path: str = "", **kwargs: Any) -> AdapterResult:
        url = (
            "https://www.googleapis.com/calendar/v3/calendars/"
            + quote(self.calendar_id, safe="")
            + "/events"
            + path
        )
        try:
            for attempt in range(2):
                token = await self.oauth.access_token(force=bool(attempt))
                headers = {"Authorization": f"Bearer {token}"}
                if self.client is not None:
                    response = await self.client.request(method, url, headers=headers, **kwargs)
                else:
                    async with httpx.AsyncClient(timeout=20) as client:
                        response = await client.request(method, url, headers=headers, **kwargs)
                if response.status_code != 401:
                    break
            if response.is_success:
                return AdapterResult(True, response.json() if response.content else {})
            message = (
                "Google Calendar access denied or revoked; reconnect Google."
                if response.status_code in (401, 403)
                else f"Google Calendar returned HTTP {response.status_code}."
            )
            return AdapterResult(False, {}, message)
        except GoogleAuthError as exc:
            return AdapterResult(False, {}, str(exc))
        except (httpx.HTTPError, ValueError):
            return AdapterResult(
                False, {}, "Could not reach Google Calendar or decode its response."
            )

    async def check(self) -> AdapterResult:
        return await self._api("GET", params={"maxResults": 1})

    async def read(self, path: str = "", **kwargs: Any) -> AdapterResult:
        return await self.list_events(**kwargs)

    async def list_events(self, start: str, end: str) -> AdapterResult:
        params = {
            "timeMin": start,
            "timeMax": end,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "250",
        }
        events: list[dict[str, Any]] = []
        while True:
            result = await self._api("GET", params=params)
            if not result.ok:
                return result
            events.extend(result.data.get("items", []))
            cursor = result.data.get("nextPageToken")
            if not cursor:
                return AdapterResult(True, {"events": events})
            params["pageToken"] = cursor

    async def create_event(self, event: dict[str, Any]) -> AdapterResult:
        return await self._api("POST", json=event)

    async def update_event(self, event_id: str, event: dict[str, Any]) -> AdapterResult:
        return await self._api("PATCH", "/" + quote(event_id, safe=""), json=event)

    async def delete_event(self, event_id: str) -> AdapterResult:
        return await self._api("DELETE", "/" + quote(event_id, safe=""))
