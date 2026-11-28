#!/usr/bin/env bash
# Usage: pre-pr.sh [base]
# The local gate before a pull request, which leaves the full gate to the pull request's CI run.
# It runs the checks of the CI docs path, the unit tests of the changed packages and of every package that depends on
# them, and the integration tests of the changed packages. pytest exit 5 (nothing collected) is success.
# The changes are taken against base, by default the merge base with origin/main, which a stacked branch overrides.
# A change that no package owns, outside documentation, names the full run and exits 1 before running anything.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v uv >/dev/null || { echo "error: uv not on PATH, run inside nix develop" >&2; exit 1; }
base=${1:-$(git merge-base origin/main HEAD)} || { echo "error: no merge base with origin/main" >&2; exit 1; }

# Committed, uncommitted and untracked changes since base.
plan=$({ git diff --name-only --no-renames "$base"; git ls-files --others --exclude-standard; } | python3 scripts/affected.py) || {
    echo "full run required, no package owns ${plan#full }: nix develop -c just ci"
    exit 1
}
read -ra itest <<<"$(sed -n 's/^itest *//p' <<<"$plan")"
read -ra unit <<<"$(sed -n 's/^unit *//p' <<<"$plan")"

pytest() {
    local rc=0
    uv run --frozen pytest "$@" || rc=$?
    if [ "$rc" -eq 5 ]; then echo "notice: no tests collected"; return 0; fi
    return "$rc"
}

scripts/ci.sh --docs
echo "== unit tests: ${unit[*]:-none}"
[ "${#unit[@]}" -eq 0 ] || pytest -n auto --dist worksteal -m "not integration and not slow" "${unit[@]}"
echo "== integration tests: ${itest[*]:-none}"
[ "${#itest[@]}" -eq 0 ] || pytest -m integration "${itest[@]}"
