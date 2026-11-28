#!/usr/bin/env bash
# Usage: itest.sh [--tier <name>] [domain | -- pytest-args...]
# Integration tests, or the tests of another tier of scripts/lib/tiers.sh, optionally limited to packages/<domain> or by pytest arguments.
# pytest exit 5 (nothing collected) is success, and exit 4 is a refusal: the T1 lock wait ran out.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v uv >/dev/null || { echo "error: uv not on PATH, run inside nix develop" >&2; exit 1; }
# --frozen runs the pytest pinned in uv.lock, and uv fails loudly when it cannot provide one.
pytest=(uv run --frozen pytest)
# shellcheck source=scripts/lib/tiers.sh
source "$(dirname "$0")/lib/tiers.sh"
tier=integration
if [ "${1:-}" = --tier ]; then
    [ $# -ge 2 ] || { echo "usage: itest.sh --tier <name> ..." >&2; exit 2; }
    tier=$2
    shift 2
fi
tier_args "$tier" || exit

case "${1:-}" in
    "") target=() ;;
    --) target=("${@:2}") ;;
    *) target=("packages/$1") ;;
esac

rc=0
"${pytest[@]}" "${tier_pytest_args[@]}" "${target[@]}" || rc=$?
if [ "$rc" -eq 5 ]; then echo "notice: no integration tests collected"; exit 0; fi
exit "$rc"
