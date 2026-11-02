#!/bin/bash
# Bootstrap Ray without Homebrew or administrator access.
set -euo pipefail

export PNPM_HOME="${PNPM_HOME:-$HOME/.local/share/pnpm}"
export PATH="$HOME/.local/bin:$PNPM_HOME:$PNPM_HOME/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"
platform="$(uname -s)"
fail() { printf '%s\n' "$*" >&2; exit 1; }
command -v curl >/dev/null || fail "Install curl, then run Install Ray again."

if ! command -v git >/dev/null || ! git --version >/dev/null 2>&1 || ! command -v python3 >/dev/null; then
  if [ "$platform" = Darwin ]; then
    echo "Ray needs Apple's Command Line Tools (Git/Python). Accept the installation dialog."
    xcode-select --install || true
    fail "Finish installing Command Line Tools, then click Install Ray again. Python 3.12 will be managed by uv."
  fi
  command -v git >/dev/null || fail "Install Git with your Linux package manager, then run Install Ray again."
fi

if ! command -v docker >/dev/null; then
  echo "Docker Desktop must be installed and its first-run setup completed: https://www.docker.com/products/docker-desktop/"
  if [ "$platform" = Darwin ]; then open "https://www.docker.com/products/docker-desktop/" || true; fi
  fail "Install Docker Desktop, open it once, then click Install Ray again."
fi
if ! docker info >/dev/null 2>&1; then
  [ "$platform" = Darwin ] || fail "Start Docker and run Install Ray again."
  echo "Starting Docker Desktop…"
  open -a Docker || fail "Open Docker Desktop and complete its setup, then retry."
  ready=0
  for ((attempt=0; attempt<90; attempt++)); do
    if docker info >/dev/null 2>&1; then ready=1; break; fi
    sleep 2
  done
  [ "$ready" = 1 ] || fail "Docker did not become ready. Complete Docker Desktop setup, then retry."
fi

if ! command -v uv >/dev/null; then
  echo "Installing uv from Astral into ~/.local/bin…"
  curl -fsSL https://astral.sh/uv/install.sh | UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh
fi
uv python install 3.12
if ! command -v pnpm >/dev/null || ! command -v node >/dev/null || ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)'; then
  echo "Installing standalone pnpm and Node 22 into your home directory…"
  curl -fsSL https://get.pnpm.io/install.sh | PNPM_VERSION=9.15.0 SHELL=/bin/bash ENV="$HOME/.bashrc" sh
  pnpm env use --global 22
fi

SCRIPT_DIR=""
if [ -f "${BASH_SOURCE[0]:-}" ]; then SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; fi
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/ray" ]; then
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
elif [ -f "./scripts/ray" ]; then
  REPO_ROOT="$PWD"
elif [ -f "./ray-ai-assistant/scripts/ray" ]; then
  REPO_ROOT="$PWD/ray-ai-assistant"
elif [ -e "./ray-ai-assistant" ]; then
  fail "ray-ai-assistant exists but is not a Ray checkout. Choose an existing folder or move it before retrying."
else
  echo "Cloning Ray..."
  git clone https://github.com/rayanali2/ray-ai-assistant.git
  REPO_ROOT="$PWD/ray-ai-assistant"
fi

cd "$REPO_ROOT"
echo "Using checkout at $REPO_ROOT (existing files are preserved)."

if [ ! -f .env ]; then
  uv run --python 3.12 python scripts/ray init --preset auto
elif [ -n "${RAY_GEMINI_API_KEY:-}" ]; then
  uv run --python 3.12 python scripts/ray configure-key
fi

uv run --python 3.12 python scripts/ray install
if [ "${RAY_FROM_DESKTOP:-0}" = 1 ]; then
  uv run --python 3.12 python scripts/ray start --no-browser
else
  uv run --python 3.12 python scripts/ray start
fi
