# Architecture Decision Records

An ADR records one significant technical decision: the context that forced it, the
choice made, the alternatives rejected, and the consequences accepted.

`/docs` is the source of truth for *what* Ray is. The ADRs are the source of truth
for *how* Ray is built and *why*. When a decision changes, add a new ADR that
supersedes the old one rather than editing history.

## Format

Every ADR uses the same sections: Status, Context, Decision, Alternatives
considered, Consequences.

Status is one of `Accepted`, `Superseded by ADR-XXXX`, or `Proposed`.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-llm-provider-abstraction.md) | LLM provider abstraction with Gemini as the default | Accepted (amended by 0015) |
| [0002](0002-postgres-pgvector.md) | PostgreSQL + pgvector as the single data store | Accepted |
| [0003](0003-local-embeddings.md) | Local sentence-transformers embeddings | Accepted (extended by 0016) |
| [0004](0004-unified-task-model.md) | One unified Task model | Accepted |
| [0005](0005-agents-as-code.md) | Agents are code modules, not database rows | Accepted |
| [0006](0006-single-user-auth.md) | Single local user and token auth for V1 | Accepted |
| [0007](0007-sse-streaming.md) | REST + Server-Sent Events instead of WebSockets | Accepted |
| [0008](0008-no-orchestration-framework.md) | Hand-written orchestrator, no agent framework in V1 | Accepted |
| [0009](0009-voice-first-architecture.md) | Voice-first architecture with wake word as a core feature | Accepted |
| [0010](0010-tool-manager-and-adapters.md) | Tool Manager with swappable integration adapters | Accepted |
| [0011](0011-frontend-stack.md) | Next.js + TypeScript + Tailwind + shadcn/ui frontend | Accepted |
| [0012](0012-backend-stack.md) | FastAPI + SQLAlchemy + Alembic backend and tooling | Accepted |
| [0013](0013-memory-policy.md) | Memory write, dedupe, and retrieval policy | Accepted |
| [0014](0014-approval-gate.md) | Explicit user approval for side-effecting tool calls | Accepted |
| [0015](0015-mock-provider-and-graceful-degradation.md) | Mock provider terminates the fallback chain; Groq deferred | Accepted |
| [0016](0016-embedding-backend-fallback.md) | Embeddings degrade to a hashing backend instead of failing | Accepted (extends 0003) |
| [0017](0017-tool-calling-and-provider-fallback.md) | Tool calling and provider fallback | Accepted |
| [0018](0018-local-voice-pipeline.md) | Local voice providers behind optional model downloads | Accepted (extends 0009) |
| [0019](0019-subscription-cli-providers.md) | Personal subscription CLI providers and ordered fallbacks | Accepted |
