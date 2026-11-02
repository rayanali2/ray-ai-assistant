# ADR-0020: Electron desktop shell

Status: Accepted

## Context

The existing macOS app is a shell launcher that opens a browser. Ray needs a
downloadable app with a dedicated window, tray, microphone access and global
voice shortcut, while retaining the existing local service stack.

## Decision

Use Electron and electron-builder in an independent `desktop/` pnpm package,
with plain JavaScript and no renderer bundler. Package unsigned arm64/x64 DMG and
ZIP artifacts on macOS, plus a Linux AppImage for local verification. Reuse the
existing 1024px macOS icon. Keep the legacy launcher as a lightweight alternative.

Locate a separate checkout via RAY_HOME, saved config or home-directory defaults.
First-run onboarding chooses a checkout or runs the bundled existing install.sh
in the home directory. The app does not embed Python, Node service dependencies,
Docker or PostgreSQL. Login-shell PATH discovery plus standard tool locations
supports GUI launches. Start Docker Desktop on macOS when needed, invoke ray start
without opening a browser, then poll backend health and HUD readiness. Startup
errors expose logs, retry and doctor output.

Browser windows use sandboxing and context isolation, with no Node integration.
The main preload exposes only a listen subscription. Audio permission is limited
to the exact localhost HUD origin; external HTTP(S) links open in the browser.
The installer uses separate restricted IPC and a content security policy.
Selecting a checkout trusts that local code. Config, bounds and logs live under
the platform application-support directory.

Closing the main window hides it. Normal quit keeps services running; explicit
stop uses ray stop (the PostgreSQL container remains running).

## Consequences

Electron increases download size but supplies mature window, tray, permission
and packaging APIs. Signing, notarization, auto-update and a self-contained
runtime remain future work. Linux checks cannot verify Gatekeeper, macOS
microphone prompts, Apple Silicon/Intel disk images or Docker Desktop activation.
