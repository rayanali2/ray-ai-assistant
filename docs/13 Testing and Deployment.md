# `/docs/13 Testing and Deployment.md`

# Ray — Testing and Deployment Requirements

## Purpose

This document defines how Ray should be tested, deployed, and maintained.

The goal is a reliable system that can continue improving without breaking existing functionality.

---

# Development Environment

Ray should support local development first.

Requirements:

* easy setup
* clear installation steps
* documented dependencies

A new developer should be able to run Ray by following the README.

---

# Testing Strategy

Testing should happen continuously.

---

# 1. Unit Testing

Purpose:

Verify individual components work correctly.

Examples:

* memory retrieval
* task creation
* database operations
* agent logic

---

# 2. Integration Testing

Purpose:

Verify systems work together.

Examples:

* frontend communicates with backend
* agents access memory
* GitHub integration works
* calendar integration works

---

# 3. User Flow Testing

Test complete scenarios.

Example:

User:

"Plan my week."

Expected:

1. Ray understands request.
2. Planning Agent activates.
3. Calendar is checked.
4. Tasks are considered.
5. Schedule is generated.

---

# 4. AI Testing

AI behavior should be evaluated.

Check:

* correct agent selection
* useful responses
* proper memory usage
* avoiding hallucinations
* explaining actions

---

# Development Checks

From the repository root, after installing development dependencies:

```sh
(cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy ray scripts && uv run lint-imports)
(cd backend && RAY_DATABASE_URL=postgresql+asyncpg://ray:ray@localhost:5433/ray_test uv run pytest -q)
(cd frontend && pnpm lint && pnpm typecheck && pnpm test)
(cd desktop && pnpm test)
```

Tests must use the dedicated `ray_test` database, never a checkout's personal `ray`
database. Google/Notion HTTP and Gemini quota behavior use mocks; passing tests do
not verify real OAuth consent, account permissions, or live model quotas.

Before considering a feature complete:

Verify:

* functionality works
* errors are handled
* documentation is updated
* existing features still work

---

# Deployment Strategy

## Initial Version

Priority:

Run locally.

Reason:

* fastest development
* free
* easier debugging
* protects personal data

---

# Future Deployment

Possible options:

## Personal Server

Advantages:

* control
* privacy
* customization

---

## Free Cloud Options

Only use if:

* sufficient free tier exists
* no unnecessary complexity

---

# Version Control

Use Git.

Requirements:

* meaningful commits
* clear history
* regular backups

---

# Release Process

Desktop releases are built by `.github/workflows/desktop.yml`: `v*` tags derive the
Electron app version from the tag and attach unsigned arm64/x64 DMG/ZIP artifacts
to GitHub Releases. Main/path builds and manual dispatch upload `Ray-macOS`
Actions artifacts. v0.2.1 uses this tag-derived versioning; untagged local builds
still use the version in `desktop/package.json` (currently 0.2.0).

`backend/scripts/release.py <version> [--message ...] [--no-commit]` updates backend
and frontend version files and CHANGELOG, and by default commits/tags locally.
Run it with `cd backend && uv run python scripts/release.py ...` so uv uses the
backend environment. It does not update `desktop/package.json`, push tags or sign
artifacts. Review/stage only intended changes before using its commit mode.

Before a major release:

1. Test functionality.
2. Verify integrations.
3. Update documentation.
4. Create version tag.
5. Record changes.

---

# Monitoring

Ray should eventually track:

* errors
* failed integrations
* performance issues

Avoid collecting unnecessary analytics.

---

# Completion Criteria

Testing and deployment are complete when:

* Ray runs reliably
* setup instructions exist
* major features have tests
* bugs can be identified
* future changes can be safely introduced
