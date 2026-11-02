# `/docs/12 Security and Privacy.md`

# Ray — Security and Privacy Requirements

## Purpose

This document defines how Ray handles user data, integrations, credentials, and permissions.

Ray is a personal AI assistant with access to private information. Security must be considered from the beginning.

---

# Core Principles

## User Ownership

All Ray data belongs to the user.

The user must control:

* stored memories
* connected accounts
* imported information
* deleted data

---

## Minimum Data Collection

Ray should only store information required for useful functionality.

Avoid storing:

* unnecessary conversation history
* duplicate information
* temporary data permanently

---

## Transparency

Ray should explain:

* what information it accessed
* what actions it performed
* what tools it used

Example:

"Used GitHub integration to analyze Starfall Sprint repository."

---

# Authentication

Ray must protect access to:

* user account
* database
* external integrations
* API keys

**V1 (ADR-0006):** a single seeded local user and a static bearer token on every request
outside `/health` and `/integrations/google/callback`. The latter uses expiring,
single-use OAuth state and PKCE rather than a bearer token (ADR-0021). FastAPI's
generated `/docs`, `/redoc` and `/openapi.json` are also public.
The backend binds to `127.0.0.1`. There is deliberately no
registration or login system — hand-rolling one for a single local user would add risk
without adding protection. Identity resolution lives in one dependency function so real
authentication can replace it later without touching any other code.

Requirements that still apply in full:

* application data/action endpoints require authentication, even locally
* credentials are never hardcoded and never logged
* the token lives in a git-ignored `.env` and is never exposed to browser JavaScript

---

# API Key Management

Secrets must never be stored directly in code.

Use:

* environment variables
* the OS keyring where available

The `integrations` table stores only a **reference** to where a secret lives (an
environment variable name or a keyring key) — never a secret value. Logs pass through a
redaction processor; do not rely on redaction to make arbitrary debug output safe.
Google OAuth tokens are stored outside the database in
`~/.local/share/ray/google-calendar.json` (or `RAY_DATA_DIR`), atomically with mode
0600. Bootstrap/Preferences persist Gemini keys in the checkout's private `.env`.

Example:

Correct:

```
OPENAI_API_KEY=stored_securely
```

Incorrect:

```
api_key="123456"
```

---

# Side-Effect Approval

**Every tool that changes state requires explicit user approval before it runs
(ADR-0014).** This is enforced by the Tool Manager, not by the model: a side-effecting
tool cannot execute without an approval record.

The user is shown the exact payload — "Create event *Coding block*, Tue 19:00–21:00" —
and approves or rejects it. Read-only tools run freely; requiring consent to read a task
list would make Ray useless.

Standing approvals ("always allow this tool") are available for low-risk internal tools,
are listed and revocable in Settings, and are **never** available for tools that write
outside Ray's own database.

---

# Prompt Injection

Ray reads untrusted content: repository files, notes, and web pages can contain text
aimed at the model. Countermeasures:

* external content is inserted into prompts inside explicit untrusted-content
  delimiters and is never treated as instructions
* credentials are held by the Tool Manager and injected at call time, so they never
  enter an agent's context and cannot be echoed out
* because every state change is gated on a human click that displays the real payload,
  a successful injection still cannot silently alter user data

---

# Integration Permissions

Every external connection should have controlled permissions.

Examples:

## GitHub

Allow:

* repository reading
* optional repository modification

Only enable write access when necessary.

---

## Calendar

Allow:

* viewing events
* creating events after user approval

---

## File Access

Ray should:

* request permission
* clearly show accessed files
* avoid unrestricted access

---

# Data Leaving the Machine

Ray must be honest about this.

* **Memory storage and embedding computation are local.** Retrieved memory text and
  tool results may be included in prompts sent to a hosted model or subscription CLI.
* **Conversation text does leave the machine** when a hosted LLM provider is selected
  (the default is Google's Gemini free tier, ADR-0001). This must be stated in the
  README and in the Settings UI.
* For local-only model generation set `RAY_LLM_PROVIDER=ollama` and
  `RAY_LLM_FALLBACK_PROVIDER=mock`. Browser speech and cloud integrations are
  independent network paths; changing the LLM does not disable them.
* Browser wake-word detection operates on speech recognition transcripts: the
  browser vendor may receive audio **before** activation. Local STT/TTS uses the
  local backend; the HUD currently supports local push-to-talk, not continuous
  local wake-word capture. Armed listening has a visible, revocable indicator.
* **The browser speech backends are a hosted service in disguise.** `RAY_STT_BACKEND=browser`
  uses the Web Speech API, and in Chrome that streams the captured audio to Google for
  transcription — the audio leaves the machine even though the code runs in the browser.
  Speech *synthesis* is local in current browsers, but is not guaranteed to be. This is
  the zero-setup fallback; optional `RAY_STT_BACKEND=local` (faster-whisper) and Piper
  are implemented. Compressed browser audio requires ffmpeg on the backend PATH.
  The UI must say which
  backend is active rather than only showing a microphone icon.
* **The API token stays server-side.** The browser talks to a Next.js route handler,
  which adds the bearer token; `RAY_API_TOKEN` is never sent to the client or exposed in
  a client bundle. Only variables intentionally prefixed for client use may be read from
  browser code.
* **A provider key must never be logged or returned by the API.** It may be persisted
  in the private gitignored `.env`, not in database integration records.
  `GET /chat/providers` reports whether a provider is configured and why not — never the
  credential. `.env` is gitignored, and the key is read through settings only
  (ADR-0015).

---

# Memory Privacy

Memory requires special handling.

Requirements:

* user can view memories
* user can delete memories
* user can disable memory categories
* Ray should avoid storing sensitive information unnecessarily

---

# Local Data Protection

If Ray runs locally:

Protect:

* database files
* configuration files
* user documents

---

# Error Handling

Errors should not reveal:

* API keys
* private information
* database details

---

# Future Security Improvements

Possible additions:

* encrypted memory
* local AI models
* advanced permission controls
* audit logs
* user activity history

---

# Completion Criteria

Security requirements are satisfied when:

* credentials are protected
* user data is controlled
* integrations require permission
* memory can be managed
* errors are safe
