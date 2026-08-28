#!/bin/bash
# Install a Linux .desktop launcher for Ray.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP_FILE="$REPO_ROOT/scripts/ray.desktop"
TARGET="$HOME/.local/share/applications/ray.desktop"

mkdir -p "$(dirname "$TARGET")"
sed "s|__RAY_REPO_ROOT__|$REPO_ROOT|g" "$DESKTOP_FILE" > "$TARGET"
chmod +x "$TARGET"

echo "Installed desktop launcher at $TARGET"
echo "Refresh with: update-desktop-database ~/.local/share/applications"
