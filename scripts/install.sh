#!/bin/bash
# One-liner install for Ray.
#
#   curl -fsSL https://raw.githubusercontent.com/rayanali2/ray-ai-assistant/main/scripts/install.sh | bash
#
# Or, from a local clone:
#
#   ./scripts/install.sh
#
# The script checks for the required tooling, clones the repo if it is not already
# on disk, runs `scripts/ray init --preset local` to create .env, then runs
# `scripts/ray install` and `scripts/ray start`.

set -euo pipefail

SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ "${BASH_SOURCE[0]}" != "bash" ] && [ "${BASH_SOURCE[0]}" != "/bin/bash" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/ray" ]; then
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
elif [ -f "./scripts/ray" ]; then
  REPO_ROOT="$PWD"
elif [ -d "./ray-ai-assistant" ]; then
  REPO_ROOT="$PWD/ray-ai-assistant"
else
  echo "Cloning Ray..."
  git clone https://github.com/rayanali2/ray-ai-assistant.git
  REPO_ROOT="$PWD/ray-ai-assistant"
fi

missing=()
command -v docker >/dev/null 2>&1 || missing+=("docker (https://docs.docker.com/get-docker/)")
command -v uv >/dev/null 2>&1 || missing+=("uv (https://docs.astral.sh/uv/)")
command -v pnpm >/dev/null 2>&1 || missing+=("pnpm (https://pnpm.io/installation)")
command -v node >/dev/null 2>&1 || missing+=("Node.js (https://nodejs.org/)")

if [ ${#missing[@]} -ne 0 ]; then
  echo "Ray needs the following tools before it can install:"
  printf '  - %s\n' "${missing[@]}"
  exit 1
fi

cd "$REPO_ROOT"

if [ ! -f .env ]; then
  ./scripts/ray init --preset local
fi

./scripts/ray install
./scripts/ray start
