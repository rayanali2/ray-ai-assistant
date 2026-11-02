# ADR-0021: Google Calendar and Notion adapters

## Status
Accepted

## Decision
Implement optional adapters using httpx, without vendor SDK dependencies. Google
uses the installed-app loopback flow on the local backend with PKCE S256 and
single-use, ten-minute state bound to the authenticated Ray user. Only the callback
is bearer-exempt: a browser redirect cannot carry Ray's token. Request only
`calendar.events` for the primary/configured calendar, not full calendar access.
Store OAuth credentials atomically in the private Ray data directory, mode 0600;
refresh access tokens automatically and discard revoked refresh tokens. The app is
single-user; these credentials are not a multi-tenant credential store.

Notion uses an internal integration token supplied through backend settings (or an
existing environment reference), API version 2022-06-28, cursor pagination and
bounded Retry-After retries. No credentials or raw authentication errors enter
tool responses. Pages must be explicitly shared with the integration.

Register cloud tools through the existing Tool Manager and specialist allow-lists.
Cloud writes always require individual approval, including when standing allow is
set. Dashboard schedule reads combine live Google events with local events without
persisting remote copies; failed remote reads never erase local schedule entries.

## Consequences
Users must configure their own Google OAuth client/consent and Notion integration.
Google testing-mode refresh tokens may expire after seven days. OAuth pending state
is process-local: restarting the backend requires restarting consent. The loopback
flow assumes a local backend; remote/multi-worker deployments need a separate
credential/session design. Notion database title column names must be supplied;
custom database schemas and background bidirectional sync are out of scope.
Mocked HTTP tests cover contracts, refresh/revocation, pagination, errors and the
actual API/approval boundaries; live consent and account permissions need a user's
credentials to verify.
