#!/bin/bash
# Build a double-clickable Ray.app for the current checkout and copy it to
# /Applications (or any target directory you pass as the first argument).
#
# Run this after `./scripts/ray install` has completed, otherwise the app will fail
# to start because dependencies and the database are not ready.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_DIR="${1:-/Applications}"
APP_NAME="Ray.app"
APP_PATH="$TARGET_DIR/$APP_NAME"

if [ ! -f "$REPO_ROOT/.env" ] || [ ! -d "$REPO_ROOT/frontend/node_modules" ]; then
  echo "This checkout has not been installed yet."
  echo "Run the quickstart first, then come back here:"
  echo "  cd $REPO_ROOT"
  echo "  ./scripts/ray init --preset local"
  echo "  ./scripts/ray install"
  exit 1
fi

mkdir -p "$TARGET_DIR"
echo "Building $APP_PATH from $REPO_ROOT..."
rm -rf "$APP_PATH"
cp -R "$REPO_ROOT/macos/Ray.app" "$APP_PATH"

# Embed the absolute repo path into the launcher so the app works from
# /Applications even though the source tree stays in your home directory.
LAUNCHER="$APP_PATH/Contents/MacOS/Ray"
sed -i.bak "/^REPO_ROOT=/s|__RAY_REPO_ROOT__|$REPO_ROOT|g" "$LAUNCHER"
rm -f "$LAUNCHER.bak"

echo "Ray is installed at $APP_PATH."
echo "Run it from Launchpad or Finder; it will start the backend and open the HUD."
