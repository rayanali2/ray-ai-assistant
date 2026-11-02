# Ray — Personal AI Assistant

Ray is a personal, Jarvis-inspired AI assistant: a single conversational surface backed
by persistent memory, specialized agents, and tools that reach into the systems its user
already lives in — calendar, GitHub, notes, and local files.

Ray is built for one person, runs locally, and costs nothing to operate.

> **Status: Phase 9–10 complete.** Phases 1–8 (foundation, conversation, memory,
> agents, productivity/integrations, voice hardening, advanced dashboard, self-improvement)
> are merged. Ray now has specialist agents for fitness, content, and finance; an
> orchestrator that routes to them; a single-command install/run script; and a macOS
> `.app` bundle builder. See the [roadmap](docs/10%20Development%20Roadmap.md) and
> [`/docs/adr`](docs/adr/) for details.

---

## What Ray does

| Capability | Description |
|---|---|
| **Conversation** | Text and voice, including wake-word activation ("Ray") |
| **Memory** | Remembers projects, goals, preferences, and learning progress, and uses them automatically |
| **Planning** | Tasks, deadlines, priorities, scheduling, and time blocking |
| **Coding mentorship** | Understands active projects and teaches rather than replacing the user's work |
| **Learning** | Explains, quizzes, tracks proficiency, and adapts depth accordingly |
| **Research** | Turns open-ended curiosity into structured, actionable plans |
| **Fitness** | Logs workouts, tracks progress, and flags recovery notes |
| **Content** | Captures ideas, drafts posts, and repurposes across formats |
| **Finance** | Tracks income/expenses and summarises spending locally |
| **Transparency** | Always reports which agent, tools, and memories produced an answer |

---

## Architecture at a glance

```
        Voice / Text
             │
   Next.js dashboard (HUD)
             │  REST + SSE
       FastAPI backend
             │
          Ray Core            context assembly, orchestration, trace
             │
      Executive Agent         routes to one specialist by default
             │
  ┌──────────┼──────────┼──────────┬──────────┬──────────┬──────────┐
Planning  Coding  Learning  Research  Fitness  Content  Finance  (code modules)
             │
       Tool Manager           permissions, approval gate, error handling
             │
  Adapters → Integrations     GitHub, calendar, Obsidian, local files
             │
  Memory service  ←→  PostgreSQL + pgvector
```

Three rules hold the design together, and are enforced structurally by import rules in
CI:

1. Agents never touch the database — only services do.
2. Agents never touch external services — only the Tool Manager does.
3. Nothing that changes state runs without explicit user approval.

---

## Technology

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic | Best AI ecosystem; async suits streaming and tool calls ([ADR-0012](docs/adr/0012-backend-stack.md)) |
| Database | PostgreSQL 16 + pgvector | One store for relational data *and* semantic memory ([ADR-0002](docs/adr/0002-postgres-pgvector.md)) |
| LLM | Provider abstraction: Gemini (default), Groq, Ollama | Never locked to one provider; degrades instead of breaking ([ADR-0001](docs/adr/0001-llm-provider-abstraction.md)) |
| Embeddings | Local `sentence-transformers` (`all-MiniLM-L6-v2`), with a dependency-free hashing backend | Free, fast, and the memory corpus never leaves the machine ([ADR-0003](docs/adr/0003-local-embeddings.md), [ADR-0016](docs/adr/0016-embedding-backend-fallback.md)) |
| Frontend | Next.js 15, React 19, TypeScript, Tailwind v4, shadcn/ui | Bespoke HUD without fighting a theme ([ADR-0011](docs/adr/0011-frontend-stack.md)) |
| Streaming | Server-Sent Events | One-directional flow; plain HTTP, reuses existing auth ([ADR-0007](docs/adr/0007-sse-streaming.md)) |
| Voice | openWakeWord, faster-whisper, Piper — all local | Voice-first from Phase 1, free, private ([ADR-0009](docs/adr/0009-voice-first-architecture.md)) |

Everything is free and open-source. The only external dependency is an LLM free tier,
and setting `RAY_LLM_PROVIDER=ollama` removes even that.

---

## Use your ChatGPT / Claude subscription

For personal use with an eligible ChatGPT Plus or Claude Pro subscription, install
the official CLIs and sign in on the machine running Ray:

```sh
npm install -g @anthropic-ai/claude-code @openai/codex
claude                 # complete Claude Code sign-in interactively
codex login            # sign in with ChatGPT, not an API key
./scripts/ray init --preset subscriptions  # add --force to replace an existing preset
./scripts/ray install
./scripts/ray start
```

Subscriptions do not include API keys. CLI access depends on your plan, vendor
terms and usage limits; Ray does not bypass those limits. No login is performed by
Ray. `./scripts/ray doctor` reports optional CLI installation/login status.

The preset uses Gemini when a Gemini key is already present, otherwise Claude Code,
then tries `claude_cli,codex_cli,ollama` with mock always last. Override
`RAY_LLM_PROVIDER` / `RAY_LLM_ROUTER_PROVIDER` to select either CLI directly.
Optional settings: `RAY_CLAUDE_CLI_MODEL`, `RAY_CODEX_CLI_MODEL`,
`RAY_CLAUDE_CLI_BINARY=claude`, `RAY_CODEX_CLI_BINARY=codex`,
`RAY_CLI_TIMEOUT_SECONDS=120`. Exported environment variables override `.env`.

CLI providers do not support Ray function/tool calling: specialists can answer in
prose but cannot execute Ray tools through these models. Claude tools are disabled;
Codex is read-only in a temporary directory (not a filesystem privacy boundary).
Codex streams completed message items, not individual tokens. Failures before the
first output fall through to the next provider; later failures end the stream.

## Quickstart

Prerequisites: Docker, Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 with
pnpm.

```bash
git clone https://github.com/rayanali2/ray-ai-assistant.git
cd ray-ai-assistant

./scripts/ray init --preset local   # creates .env (or gemini/fast if you have a key)
# Optionally edit .env to set RAY_GEMINI_API_KEY or RAY_USER_NAME.

./scripts/ray install               # dependencies, Postgres, migrations, seed data
./scripts/ray start                 # opens http://localhost:3000
```

Or run everything at once:

```bash
./scripts/install.sh
```

One-line installer (macOS / Linux):

```bash
curl -fsSL https://raw.githubusercontent.com/rayanali2/ray-ai-assistant/main/scripts/install.sh | bash
```

Open http://localhost:3000 and the dashboard shows the seeded project, tasks, schedule,
memories, agents, and workflows. Control the running services with `status`, `stop`, and `logs`.
Run `./scripts/ray doctor` to verify your local setup.

### Install the Mac app

Download the matching **arm64** (Apple Silicon) or **x64** (Intel) `.dmg` from
GitHub **Releases**, or the **Ray-macOS** artifact in the **Desktop** Actions workflow.
Open the disk image and drag **Ray.app** to **Applications**.

The app is currently unsigned: right-click → **Open** on first launch. If macOS
still quarantines the downloaded app, after verifying its source run:

```sh
xattr -dr com.apple.quarantine /Applications/Ray.app
```

Click **Install Ray** to bootstrap without Homebrew or terminal commands. Ray
installs missing uv/Python 3.12 and standalone pnpm/Node 22 into your home directory
(no sudo), preserving existing compatible tools. If Git/Python is missing on macOS,
accept Apple's Command Line Tools dialog and click Install Ray again when it finishes.
Docker Desktop still requires its own installation/first-run setup: Ray opens its
download page if missing, or starts it and waits when installed.
The desktop download manages a separate checkout rather than bundling the database/runtime.
On launch Ray checks `RAY_HOME`, then `~/Library/Application Support/Ray/config.json`
(`repoPath`), then `~/ray-ai-assistant` and `~/Ray`. If none exists, choose an existing
folder containing `scripts/ray` or click **Install Ray** to run the existing installer
into `~/ray-ai-assistant`. Installation output is displayed in the window; existing
checkouts and configuration are preserved on retry. Desktop installation does not
open a separate browser.

For **real AI chat**, paste an optional **Gemini API key** from
[Google AI Studio](https://aistudio.google.com/) before installing. It is passed to
the installer privately and saved only in the checkout's gitignored `.env` (owner-only
permissions), never in desktop config or logs. Selection order for a fresh install:
Gemini key → signed-in Claude/Codex CLI → local Ollama. Only installed **and logged-in**
CLIs are selected. With neither a key, a signed-in CLI nor a running Ollama/model,
Ray explicitly warns that responses are canned; add a key later through
**Preferences → Save key and restart**, or install Ollama and pull `llama3.2`.
The HUD shows the last answering provider and warns when mock fallback is used.
No cloud account, subscription login or Ollama model is created automatically.

The tray and normal application menu offer Show, Start/Stop/Restart, logs, doctor
and Preferences (change checkout or Gemini key). **Cmd+Shift+Space** focuses Ray and invokes the
same action as the microphone button; local voice must be configured if Electron
does not provide browser speech recognition. **Cmd+Q** quits the app **without
stopping services**; choose **Quit and stop services** for an explicit shutdown.
Stop uses `scripts/ray stop`: backend/frontend stop, but the PostgreSQL container
remains running. Closing the main window hides it to the tray. Window bounds and
checkout choice are remembered; `RAY_HOME` overrides the saved checkout on launch.
Switching checkouts asks before stopping the previous checkout's services.
Logs live in `~/Library/Application Support/Ray/logs` (service logs in `<checkout>/.ray`).

To build locally on macOS:

```sh
cd desktop
pnpm install
pnpm dist:mac  # unsigned DMG + ZIP, arm64 and x64, in desktop/dist/
```

Linux verification: `cd desktop && pnpm install && pnpm dist:linux`, then run the
AppImage (or `pnpm dev`). Linux uses Ctrl+Shift+Space and stores desktop config/logs
under `~/.config/Ray`. No auto-update, signing or notarization is configured yet.

### Lightweight macOS launcher alternative

The `.app` wrapper is built after you have run the terminal quickstart once:

```bash
./scripts/build-macos-app.sh     # copies macos/Ray.app to /Applications
```

Run it from Launchpad or Finder; it starts the backend and opens the HUD. `Ray.app`
wraps `./scripts/ray start` and references this checkout, so keep the repo in place
or rebuild the app after moving it. If you have not run `./scripts/ray install` yet,
the app will fail to start because dependencies and the database are not initialized.

### Linux desktop entry

```bash
./scripts/build-linux-desktop.sh
```

### Choosing a model

Ray runs with **no** model configured — it answers from a labelled `mock` provider that
tells you what to set (ADR-0015). To get real answers, pick either end of the chain:

```bash
# Hosted, best quality, free tier. Key from https://aistudio.google.com/apikey
RAY_GEMINI_API_KEY=…

# Or fully local, nothing leaves the machine:
#   ollama pull llama3.2
RAY_LLM_PROVIDER=ollama
```

The chain is `RAY_LLM_PROVIDER → RAY_LLM_FALLBACK_PROVIDER → mock`, tried in order. A
rate limit, an outage, a missing key, or a model that has not been pulled moves to the
next link and records the degradation in the response trace, so a failing provider
degrades Ray rather than breaking it. `GET /chat/providers` shows the resolved chain and
why anything in it is unusable.

Adding a provider is one file in `backend/ray/llm/providers/` plus an environment
variable; `lint-imports` enforces that no vendor SDK is imported outside `ray/llm/`.

### Talking to Ray

Type in the composer, or use voice: **⏺ push-to-talk** for one request, or arm the wake
word and say *"Ray, …"*. Spoken replies are off by default (🔇) because they should be a
choice, and when on, Ray speaks a variant of the answer written to be *heard* — no code
blocks, no markdown.

Voice needs a Chromium-based browser and a microphone permission granted from a click;
`browser` speech recognition sends the audio to Google, which is why the control names
the active backend (`docs/12`). Everything works without a microphone — voice is an
input, not a requirement.

#### Running voice locally (no cloud STT/TTS)

Local browser recordings (WebM/Ogg/MP4) also require **ffmpeg** on the service PATH.
On macOS, use a macOS binary linked from [ffmpeg.org](https://ffmpeg.org/download.html)
and place the `ffmpeg` executable in `~/.local/bin` (no Homebrew required), or use
`brew install ffmpeg` if you already use Homebrew. On Debian/Ubuntu, install it with
`sudo apt install ffmpeg`. Restart Ray afterward; `./scripts/ray doctor` reports
whether it is found. The bootstrap installer does not download third-party ffmpeg
binaries automatically. Missing ffmpeg produces a clear voice error, not a bogus
transcription. Raw PCM and WAV input do not require ffmpeg.

Install the optional voice dependencies and download the models once:

```bash
cd backend
uv sync --group voice
uv run python scripts/download_voice_models.py   # caches ~/.local/share/ray/voices
```

Then set in `.env`:

```bash
RAY_STT_BACKEND=local
RAY_TTS_BACKEND=local
RAY_WAKE_WORD_ENABLED=true
```

`download_voice_models.py` fetches a small Piper voice model and pre-loads the Whisper
`tiny` model so first use is fast. Server-side wake word works without `openwakeword`:
Ray runs a tiny faster-whisper keyword spotter on the microphone stream, so "Ray" or
"Jarvis" activates even when no dedicated `.tflite` wake model is installed. A real
openWakeWord model can be configured with `RAY_WAKE_WORD_MODEL` when it is available.

Under each answer, the collapsed trace line shows what actually happened: which agent
answered, which provider was used, how many memories were retrieved, and whether a
fallback kicked in. Every line is recorded by the code that ran the step, so it cannot
be a story the model told.

### What Ray remembers

Ray learns from a conversation *after* it answers, so remembering never costs latency,
and it stores a fact only if it is durable and would change a future answer. Saying
**"Ray, remember that…"** stores something verbatim, no judgement applied.

Everything Ray knows is at **`/memory`** (the HUD's Memory panel links to it): search it
by keyword or semantically with the retrieval scores shown, edit or delete any row, see
where each memory came from and how often it has been used, and switch whole categories
off. Disabling a category stops both retrieval and future writes without deleting
anything; deleting takes effect on Ray's very next answer.

Embeddings run locally. Install the model backend with `uv sync --group embeddings`
(~2 GB of torch); without it Ray falls back to a dependency-free hashing embedder that
matches on shared words rather than meaning ([ADR-0016](docs/adr/0016-embedding-backend-fallback.md)).

### Google Calendar and Notion integrations

Local calendar/ICS and Obsidian remain available without cloud credentials. Cloud
reads go to the selected service; writes always require explicit approval in Ray,
even if a tool has an "always allow" permission.

**Google Calendar**

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/),
   enable **Google Calendar API**, and configure the OAuth consent screen: choose
   **External**, add yourself as a **test user** while the app is in testing.
2. Create an OAuth client ID of type **Desktop app**. Set these values in the
   checkout's gitignored `.env` (not in the HUD's credentials-reference field):
   ```dotenv
   RAY_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   RAY_GOOGLE_CLIENT_SECRET=your-client-secret
   ```
3. Restart Ray, then run **`./scripts/ray connect google`**, or open HUD
   **Settings → Integrations → Connect Google Calendar**. Consent opens in your
   browser and redirects to `http://127.0.0.1:8000/integrations/google/callback`.
   Keep the local backend running during this step; return to Ray and refresh
   Settings after the success message. Remote-only deployments are not supported
   by this installed-app loopback flow.
4. Ray requests only `https://www.googleapis.com/auth/calendar.events`, uses
   single-use state and PKCE, and saves refresh/access tokens in
   `~/.local/share/ray/google-calendar.json` with mode **0600** (override the data
   directory with **`RAY_DATA_DIR`**). Tokens are not returned to the HUD or agents.
   Access tokens refresh automatically. Re-run the connect command if access is
   revoked; Google testing-mode refresh tokens can expire after seven days.

Upcoming Google events appear beside local events in the dashboard schedule.
The Planning agent has `google_calendar.list`, `.create`, `.update`, and `.delete`
tools. The default calendar is `primary`; an integration's optional
`config.calendar_id` selects another calendar. This is live access, not a
background/bidirectional database sync. Google failures leave local events intact.
To disconnect, revoke Ray in your Google account and remove its local token file;
you can also disable the integration in Settings.

**Notion**

1. Visit [notion.so/profile/integrations](https://www.notion.so/profile/integrations),
   create an **internal integration**, and give it read/insert/update capabilities.
2. Set **`RAY_NOTION_TOKEN`** in `.env` to its internal integration secret and
   restart Ray. For each target page/database, use **••• → Connections** to share
   it with the integration. An API token alone does not grant page access.
3. In **Settings → Integrations**, add **Knowledge → Notion**, then **Check**.
   Leave the credentials reference empty to use `RAY_NOTION_TOKEN`, or supply an
   environment-variable reference (never paste the secret into that field).
4. Ask the Research agent to search/read shared pages/databases, create a page, or
   append text. Tools are `notion.search`, `.read`, `.create`, and `.append`.
   Creation takes a parent page/database ID; for a database, provide its title
   column name with `title_property` (default `Name`). Database templates/required
   custom properties are not inferred. Reading converts paginated/nested blocks
   to Markdown; writes insert plain-text paragraphs, not a Markdown parser.

Notion uses API version `2022-06-28`, follows pagination, and honors `Retry-After`
on 429s with bounded retries. Long throttling reports an error rather than hanging.
`ray doctor`, `/health` diagnostics, and HUD Settings expose local configuration
status; **Check** verifies live credentials/access. No credentials are bundled.

### Health, export, and releases

* `GET /health` returns a compact diagnostics map (database, LLM, voice, integrations).
* `GET /system/diagnostics` gives a detailed self-diagnosis with actionable suggestions.
* `GET /system/export` returns a complete, user-owned JSON snapshot of all Ray data.
* `backend/scripts/release.py` bumps the version across `pyproject.toml`, `ray/version.py`,
  and `frontend/package.json`, prepends the changelog, and optionally tags the release.

Streaming can also be watched from the terminal:

```bash
curl -N -H "Authorization: Bearer $RAY_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"Hello"}' http://127.0.0.1:8000/chat/message
```

### Development

```bash
# Backend: lint, types, architecture boundaries, tests
cd backend
uv run ruff check . && uv run mypy ray scripts && uv run lint-imports && uv run pytest

# Behavioural evaluation: does memory actually change Ray's answers? (docs/15)
uv run pytest tests/eval

# Frontend: regenerate the API types after changing a response shape
cd frontend && pnpm generate:api && pnpm lint && pnpm typecheck && pnpm test

# Optional: run the same checks on every commit
pre-commit install
```

The import boundaries from ADR-0012 (`agents/` may not import `db/`; only `services/`
touches the database) are checked by `lint-imports` in CI, so the layering cannot rot
quietly.

---

## Privacy

* Memory, embeddings, and pre-activation microphone audio **never leave the machine**.
* Conversation text **is** sent to the configured LLM provider. The default is Google's
  Gemini free tier; `RAY_LLM_PROVIDER=ollama` keeps everything local.
* The API always requires a bearer token and binds to `127.0.0.1` by default.
* No secret is ever stored in the database — only a reference to where it lives.

Details in [`docs/12 Security and Privacy`](docs/12%20Security%20and%20Privacy.md).

---

## Documentation

`/docs` is the source of truth for *what* Ray is. `/docs/adr` is the source of truth for
*how* it is built and *why*.

| | |
|---|---|
| [00 Vision](docs/00%20Vision.md) | What Ray is for |
| [01 Product Requirements](docs/01%20Product%20Requirements.md) | Functional requirements and MVP criteria |
| [02 Technical Architecture](docs/02%20Technical%20Architecture.md) | System structure |
| [03 Agent Specifications](docs/03%20Agent%20Specifications.md) | Each agent's purpose, tools, and limits |
| [04 Integrations and Tool System](docs/04%20Integrations%20and%20Tool%20System.md) | Tool Manager, adapters, priority |
| [05 Memory System](docs/05%20Memory%20System.md) | Memory model and behaviour |
| [06 Database and Data Model](docs/06%20Database%20and%20Data%20Model.md) | Schema |
| [07 Learning and Teaching System](docs/07%20Learning%20and%20Teaching%20System.md) | How Ray teaches |
| [08 API Specification](docs/08%20API%20and%20Backend%20Interface%20Specification.md) | Endpoints and streaming contract |
| [09 UI and UX Specification](docs/09%20UI%20and%20UX%20Specification.md) | Dashboard and components |
| [10 Development Roadmap](docs/10%20Development%20Roadmap.md) | **Canonical phase order** |
| [12 Security and Privacy](docs/12%20Security%20and%20Privacy.md) | Data handling and approval model |
| [13 Testing and Deployment](docs/13%20Testing%20and%20Deployment.md) | Testing strategy and release process |
| [15 Evaluation](docs/15%20Evaluation.md) | How AI behaviour is measured |
| [ADRs](docs/adr/) | Every resolved technical decision |
