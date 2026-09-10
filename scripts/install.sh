#!/bin/bash
# One-liner install for Ray.
#
#   curl -fsSL https://raw.githubusercontent.com/rayanali2/ray-ai-assistant/main/scripts/install.sh | bash
#
# Or, from a local clone:
#
#   ./scripts/install.sh
#
# The script checks for the required tooling, then runs `scripts/ray install`
# and `scripts/ray start`.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

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
./scripts/ray install
./scripts/ray start
