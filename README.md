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

### macOS app bundle

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
