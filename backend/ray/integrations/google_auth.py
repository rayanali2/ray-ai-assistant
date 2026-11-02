"""Installed-app OAuth with PKCE; credentials never enter tool results."""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import tempfile
import time
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import httpx

from ray.config import Settings, get_settings

REDIRECT_URI = "http://127.0.0.1:8000/integrations/google/callback"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleAuthError(Exception):
    pass


class GoogleOAuth:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.client = client
        self.path = settings.data_dir.expanduser() / "google-calendar.json"
        self.pending: dict[str, tuple[str, float, str]] = {}
        self.lock = asyncio.Lock()

    def status(self) -> str:
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            return "not configured: set RAY_GOOGLE_CLIENT_ID and RAY_GOOGLE_CLIENT_SECRET"
        return (
            "connected"
            if self._load().get("refresh_token")
            else "not connected: run ./scripts/ray connect google"
        )

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(data, handle)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def auth_url(self, user_id: str) -> str:
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            raise GoogleAuthError(self.status())
        now = time.time()
        self.pending = {k: v for k, v in self.pending.items() if v[1] > now}
        if len(self.pending) >= 100:
            raise GoogleAuthError("Too many pending sign-ins. Try again in ten minutes.")
        verifier = secrets.token_urlsafe(48)
        state = secrets.token_urlsafe(32)
        self.pending[state] = (verifier, now + 600, user_id)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": self.settings.google_client_id,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "scope": "https://www.googleapis.com/auth/calendar.events",
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )

    async def _token(self, payload: dict[str, str]) -> dict[str, Any]:
        payload.update(
            client_id=self.settings.google_client_id,
            client_secret=self.settings.google_client_secret,
        )
        try:
            if self.client is not None:
                response = await self.client.post(TOKEN_URL, data=payload)
            else:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.post(TOKEN_URL, data=payload)
            body = response.json()
            if not isinstance(body, dict):
                raise GoogleAuthError("Google OAuth returned an invalid response. Please retry.")
            if not response.is_success:
                if body.get("error") == "invalid_grant":
                    if payload.get("grant_type") == "refresh_token":
                        self.path.unlink(missing_ok=True)
                    raise GoogleAuthError(
                        "Google token revoked or expired. Run ./scripts/ray connect google again."
                    )
                raise GoogleAuthError(
                    f"Google OAuth failed (HTTP {response.status_code}). "
                    "Check your client configuration and reconnect."
                )
            if not body.get("access_token"):
                raise GoogleAuthError(
                    "Google did not return an access token. Reconnect Google Calendar."
                )
            return dict(body)
        except (httpx.HTTPError, ValueError, OSError) as exc:
            raise GoogleAuthError(
                "Could not complete Google OAuth. Check network/client configuration and retry."
            ) from exc

    async def callback(self, code: str, state: str) -> str:
        entry = self.pending.pop(state, None)
        if entry is None or entry[1] <= time.time():
            raise GoogleAuthError("Invalid or expired OAuth state. Start Google connection again.")
        if not code:
            raise GoogleAuthError(
                "Google consent was denied or no authorization code was returned."
            )
        async with self.lock:
            data = await self._token(
                {
                    "code": code,
                    "code_verifier": entry[0],
                    "redirect_uri": REDIRECT_URI,
                    "grant_type": "authorization_code",
                }
            )
            if not data.get("refresh_token"):
                raise GoogleAuthError(
                    "No refresh token returned. Revoke Ray's Google access "
                    "and reconnect with consent."
                )
            data["expires_at"] = time.time() + float(data.get("expires_in", 3600)) - 60
            self._store(data)
        return entry[2]

    async def access_token(self, *, force: bool = False) -> str:
        async with self.lock:
            data = self._load()
            if not data.get("refresh_token"):
                raise GoogleAuthError(self.status())
            if (
                not force
                and data.get("access_token")
                and float(data.get("expires_at", 0)) > time.time()
            ):
                return str(data["access_token"])
            fresh = await self._token(
                {"grant_type": "refresh_token", "refresh_token": str(data["refresh_token"])}
            )
            data.update(fresh)
            data["expires_at"] = time.time() + float(fresh.get("expires_in", 3600)) - 60
            self._store(data)
            return str(data["access_token"])

    def _store(self, data: dict[str, Any]) -> None:
        try:
            self._save(data)
        except OSError as exc:
            raise GoogleAuthError(
                "Cannot save Google tokens. Check permissions on RAY_DATA_DIR."
            ) from exc


@lru_cache
def get_google_oauth() -> GoogleOAuth:
    return GoogleOAuth(get_settings())
