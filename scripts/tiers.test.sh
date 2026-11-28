#!/usr/bin/env bash
# Self-test for lib/tiers.sh: every marker registered in pyproject.toml has a tier row, a marker without one fails, the unit
# tier keeps its expression, and an unknown tier is refused. TIERS_PYPROJECT points the marker read at another file.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$here/.."
# shellcheck source=scripts/lib/tiers.sh
source "$(dirname "$0")/lib/tiers.sh"

pass=0
ok() { echo "ok   $*"; pass=$((pass + 1)); }
fail() { echo "FAIL $*"; exit 1; }

markers=$(python3 - "${TIERS_PYPROJECT:-pyproject.toml}" <<'PY'
import sys, tomllib
with open(sys.argv[1], "rb") as f:
    for m in tomllib.load(f)["tool"]["pytest"]["ini_options"]["markers"]:
        print(m.split(":")[0].strip())
PY
)
[ -n "$markers" ] || fail "no markers read from pyproject.toml"
for m in $markers; do
    [ -n "${TIER_EXPR[$m]:-}" ] || fail "marker '$m' has no tier row in scripts/lib/tiers.sh"
done
ok "every registered marker has a tier row"

tier_args unit
for m in integration slow e2e; do
    [[ " ${tier_pytest_args[1]} " == *" not $m "* || "${tier_pytest_args[1]}" == *" not $m" ]] || fail "the unit tier does not leave out $m"
done
ok "the unit tier leaves out integration, slow and e2e"

rc=0
(tier_args nonsense) 2>/dev/null || rc=$?
[ "$rc" -eq 2 ] || fail "an unknown tier exited $rc, not 2"
ok "an unknown tier is refused with 2"

echo "tiers: $pass checks passed"
