#!/bin/bash
# Build a double-clickable Ray.app for the current checkout and copy it to
# /Applications (or any target directory you pass as the first argument).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_DIR="${1:-/Applications}"
APP_NAME="Ray.app"
APP_PATH="$TARGET_DIR/$APP_NAME"

echo "Building $APP_PATH from $REPO_ROOT..."
rm -rf "$APP_PATH"
cp -R "$REPO_ROOT/macos/Ray.app" "$APP_PATH"

# Embed the absolute repo path into the launcher so the app works from
# /Applications even though the source tree stays in your home directory.
LAUNCHER="$APP_PATH/Contents/MacOS/Ray"
sed -i.bak "s|__RAY_REPO_ROOT__|$REPO_ROOT|g" "$LAUNCHER"
rm -f "$LAUNCHER.bak"

echo "Ray is installed at $APP_PATH."
echo "Run it from Launchpad or Finder; it will start the backend and open the HUD."
