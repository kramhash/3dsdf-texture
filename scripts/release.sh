#!/usr/bin/env bash
# Release checks, then (with --publish) tag, push and create the GitHub release.
#
#   scripts/release.sh 0.1.0            # checks + build into dist/, publishes nothing
#   scripts/release.sh 0.1.0 --publish  # same, then tag v0.1.0, push, gh release create
#
# Needs: Blender (BLENDER), KTX-Software's `ktx` (KTX_BIN), uv (for ruff), gh (publish only).
set -euo pipefail
BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
KTX_BIN="${KTX_BIN:-ktx}"
cd "$(dirname "$0")/.."

version="${1:?usage: scripts/release.sh <version> [--publish]}"
publish="${2:-}"
zip="dist/sdf_texture-$version.zip"
step() { printf '\n== %s\n' "$*"; }
fail() { printf 'release: %s\n' "$*" >&2; exit 1; }

step "version $version in manifest and CHANGELOG"
manifest_version=$(sed -n 's/^version = "\(.*\)"/\1/p' extension/blender_manifest.toml)
[ "$manifest_version" = "$version" ] || fail "manifest version is $manifest_version"
grep -qx "## $version" CHANGELOG.md || fail "CHANGELOG.md has no '## $version' section"

step "clean working tree"
[ -z "$(git status --porcelain)" ] || fail "uncommitted changes"

step "tests"
tests/run.sh

step "samples are up to date"
samples/build.sh >/dev/null
git diff --exit-code --stat -- viewer-three/public/sdf godot-sample/sdf samples/suzanne.glb \
  || fail "committed samples changed; commit the rebuilt samples"

step "ktx validate"
command -v "$KTX_BIN" >/dev/null || fail "ktx not found; set KTX_BIN to KTX-Software's ktx"
for fmt in r16f r32f r8; do
  "$KTX_BIN" validate "samples/out/$fmt/Suzanne.sdf.ktx2"
done

step "ruff"
uvx ruff check extension scripts tests

step "extension validate + build"
"$BLENDER" -b --factory-startup --command extension validate extension
mkdir -p dist
rm -f "$zip"
"$BLENDER" -b --factory-startup --command extension build --source-dir extension --output-dir "$PWD/dist"
[ -f "$zip" ] || fail "build did not produce $zip"

step "zip contents"
listing=$(unzip -Z1 "$zip")
echo "$listing"
for required in blender_manifest.toml LICENSE __init__.py ui.py core/batch.py core/writers/ktx2.py; do
  grep -qx "$required" <<<"$listing" || fail "$required missing from $zip"
done
if grep -E '(^|/)(cli\.py|__pycache__/|tests/)' <<<"$listing"; then
  fail "unexpected files in $zip"
fi

if [ "$publish" != "--publish" ]; then
  step "checks passed; $zip is ready (rerun with --publish to release)"
  exit 0
fi

step "publish v$version"
notes=$(mktemp)
awk -v v="## $version" '$0 == v {on = 1; next} /^## / {on = 0} on' CHANGELOG.md >"$notes"
git tag -a "v$version" -m "v$version"
git push origin HEAD "v$version"
gh release create "v$version" "$zip" --title "v$version" --notes-file "$notes"
rm -f "$notes"
