#!/usr/bin/env bash
# Run the headless test suite. Extra args go to the test script (e.g. --timing).
set -euo pipefail
BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
cd "$(dirname "$0")/.."
exec "$BLENDER" -b --factory-startup --python-exit-code 1 --python tests/run_tests.py -- "$@"
