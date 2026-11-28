#!/usr/bin/env bash
# Usage: test.sh [pytest-args...]
# Unit tests: the unit tier of scripts/lib/tiers.sh, optionally limited by pytest arguments.
# pytest exit 5 (nothing collected) is success.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v uv >/dev/null || { echo "error: uv not on PATH, run inside nix develop" >&2; exit 1; }
# --frozen runs the pytest pinned in uv.lock, and uv fails loudly when it cannot provide one.
pytest=(uv run --frozen pytest)
# shellcheck source=scripts/lib/tiers.sh
source "$(dirname "$0")/lib/tiers.sh"
tier_args unit

# One worker per core, idle workers steal queued tests so one slow module does not set the wall time. Pass -n0 to run serial.
rc=0
"${pytest[@]}" -n auto --dist worksteal "${tier_pytest_args[@]}" "$@" || rc=$?
if [ "$rc" -eq 5 ]; then echo "notice: no tests collected"; exit 0; fi
exit "$rc"
