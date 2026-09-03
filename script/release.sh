#!/usr/bin/env bash
# Set the version in pyproject.toml and the integration manifest, commit, and
# create the matching git tag.
#
# Usage: release.sh <major|minor|patch|X.Y.Z>
#
# Home Assistant reads the version from custom_components/spinev/manifest.json
# and HACS offers an update when a new tag is released, so the two files have
# to agree with the tag.
set -euo pipefail

bump="${1:?usage: release.sh <major|minor|patch|X.Y.Z>}"

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
manifest="$repo/custom_components/spinev/manifest.json"
cd "$repo"

if [ -n "$(git status --porcelain)" ]; then
  echo "working tree not clean, commit or stash changes first" >&2
  exit 1
fi

case "$bump" in
  major | minor | patch) uv version --bump "$bump" ;;
  [0-9]*.[0-9]*.[0-9]*) uv version "$bump" ;;
  *)
    echo "usage: release.sh <major|minor|patch|X.Y.Z>" >&2
    exit 1
    ;;
esac

version="$(uv version --short)"
tag="v${version}"

if git rev-parse -q --verify "refs/tags/${tag}" >/dev/null; then
  git checkout -- pyproject.toml uv.lock
  echo "tag ${tag} already exists" >&2
  exit 1
fi

python3 - "$manifest" "$version" <<'PY'
import pathlib
import re
import sys

path, version = pathlib.Path(sys.argv[1]), sys.argv[2]
text = path.read_text()
patched, count = re.subn(r'"version": "[^"]*"', f'"version": "{version}"', text)
if count != 1:
    sys.exit(f"expected one version key in {path}, found {count}")
path.write_text(patched)
PY

# An explicit version that is already the current one leaves nothing to commit,
# which is how an existing version gets its first tag.
if [ -n "$(git status --porcelain)" ]; then
  git add pyproject.toml uv.lock "$manifest"
  git commit -m "chore(release): ${tag}"
fi

git tag -a "${tag}" -m "${tag}"

echo "version ${version}, tagged ${tag}"
echo "run the 'Release: Push Tags to Origin' task (or 'git push --follow-tags') to publish"
echo "CI verifies the tag against both versions, runs the tests, then creates the GitHub release"
