# Changelog

All notable changes to Ray are documented in this file. Releases are tagged from
`main`. Backend/frontend version maintenance uses
`cd backend && uv run python scripts/release.py <version>`; desktop tag builds
derive their app version from the `v*` tag independently.

## Unreleased

* Google Calendar installed-app OAuth/PKCE, private token refresh, approved event
  writes and merged dashboard reads; Notion paginated search/read and approved writes.
* Gemini per-model quota cooldowns, configurable Flash Lite fallback, quota/reset
  diagnostics and explicit mock notices for agent replies only.
* Trace attribution uses the actual answering provider, not the configured primary.
* Documentation reconciled with current bootstrap, voice privacy and release behavior.

## [0.2.1]

* Desktop release app metadata and artifact names now derive from the release tag,
  avoiding DMGs named with an older static package version.
* The Mac app manages a local checkout with user-local runtime bootstrap, optional
  Gemini key onboarding, provider diagnostics and official subscription CLI support.
* Local STT decodes WebM/Ogg/MP4 using ffmpeg; Ollama streaming can fall back on
  retryable HTTP failures before any output.
