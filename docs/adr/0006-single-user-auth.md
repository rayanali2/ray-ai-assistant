# ADR-0006 — Single local user and token auth for V1

## Status

Accepted. Supersedes the `/auth/register|login|logout` endpoints in `docs/08` for V1.

Amended by ADR-0021: Google's loopback callback is bearer-exempt and protected by
single-use expiring state plus PKCE. Health and FastAPI's generated documentation
are public. Other application data/action endpoints still require the bearer token.

## Context

`docs/08` specified a full registration and session system. `docs/01` says Ray V1 is for
exactly one user, and `docs/13` says it runs locally. Building registration, password
hashing, session management, and password reset for a single user on `localhost` is
work that produces no capability, and a hand-rolled auth system is more likely to
create a security problem than to solve one.

At the same time, `docs/12` correctly insists that the API is not wide open: the backend
can read files, call GitHub, and hold personal memory, so any process on the machine
reaching it unauthenticated is a real risk.

## Decision

**V1: one seeded user row, and a single static bearer token guarding the API.**

* The user is created by `scripts/seed.py` and identified by `RAY_USER_ID`. Every table
  keeps its `user_id` foreign key, so the data model is already multi-user shaped.
* Every request outside `/health` requires `Authorization: Bearer $RAY_API_TOKEN`.
  The token is generated at setup, stored in `.env` (git-ignored), and never logged.
* The backend binds to `127.0.0.1` by default. It is not reachable off the machine
  unless the user deliberately changes that.
* There is a single `get_current_user()` FastAPI dependency. It is the *only* place that
  resolves identity, so replacing it with real auth later is a one-file change.

**Future (not V1):** if Ray ever becomes multi-user or is exposed beyond localhost,
replace `get_current_user()` with OIDC or session cookies. The endpoint shapes in
`docs/08` are retained there as the future specification.

## Alternatives considered

* **No auth at all.** Simplest, and defensible on a single-user machine — but any local
  process or a stray `0.0.0.0` bind would expose personal memory and file/GitHub tools.
  The cost of a bearer-token check is one dependency function.
* **Full JWT/session auth now.** Days of work, no user-visible benefit, and it invites
  a home-grown crypto mistake. Rejected.

## Consequences

* The frontend must attach the token; in local dev it is injected server-side by the
  Next.js route handlers so the token is never exposed to browser JavaScript.
* Losing the token means editing `.env` — acceptable for one user.
* `docs/08` needs its auth section rewritten to describe V1 reality with the full scheme
  moved under "Future".
