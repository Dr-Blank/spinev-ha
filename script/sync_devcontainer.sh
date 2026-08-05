#!/usr/bin/env bash
# Copy the integration into the Home Assistant devcontainer's config directory.
#
# The devcontainer bind mounts ha-core from the host, so writing into its
# gitignored config/ directory lands the integration inside the container
# without rebuilding it. Home Assistant loads custom integrations at startup,
# so restart it after running this.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/custom_components/spinev"
DEST="${HA_CORE:-$HOME/projects/ha-core}/config/custom_components"

mkdir -p "$DEST"
rm -rf "${DEST:?}/spinev"
cp -r "$SRC" "$DEST/spinev"
find "$DEST/spinev" -name '__pycache__' -type d -prune -exec rm -rf {} +

echo "installed to $DEST/spinev"
