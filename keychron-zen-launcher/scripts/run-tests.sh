#!/usr/bin/env bash
# Run the test suite. No test framework to install; it is all unittest.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec env PYTHONPATH="${ROOT}/src" python3 -m unittest discover -s tests -t . "$@"
