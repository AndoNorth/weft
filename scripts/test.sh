#!/usr/bin/env bash
# Usage: test.sh [pytest-args...]
# Unit tests: everything not marked integration, slow or e2e, optionally limited by pytest arguments.
# pytest exit 5 (nothing collected) is success.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v uv >/dev/null || { echo "error: uv not on PATH, run inside nix develop" >&2; exit 1; }
# --frozen runs the pytest pinned in uv.lock, and uv fails loudly when it cannot provide one.
pytest=(uv run --frozen pytest)

# One worker per core, idle workers steal queued tests so one slow module does not set the wall time. Pass -n0 to run serial.
rc=0
"${pytest[@]}" -n auto --dist worksteal -m "not integration and not slow and not e2e" "$@" || rc=$?
if [ "$rc" -eq 5 ]; then echo "notice: no tests collected"; exit 0; fi
exit "$rc"
