#!/usr/bin/env bash
# Link the integration into the Home Assistant devcontainer's config directory.
#
# Requires the devcontainer to bind mount this repository at
# /workspaces/spinev-ha, so the symlink resolves inside the container. Edits on
# the host are then live; Home Assistant still needs a restart to pick up
# changed Python.
set -euo pipefail

DEST="${HA_CORE:-$HOME/projects/ha-core}/config/custom_components"

mkdir -p "$DEST"
rm -rf "${DEST:?}/spinev"
ln -s /workspaces/spinev-ha/custom_components/spinev "$DEST/spinev"

echo "linked $DEST/spinev -> /workspaces/spinev-ha/custom_components/spinev"
