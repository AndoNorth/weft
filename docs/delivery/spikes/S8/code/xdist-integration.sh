#!/usr/bin/env bash
# Usage: xdist-integration.sh <variant> <shard> <out dir>
# Runs the integration tier of one shard of scripts/ci-shards.sh the way a variant says and prints one result line.
#   n0     one process, the layout CI uses today
#   n2     two xdist workers, every test as is
#   n2split two workers for the tests without the pair marker, then one process for the pair tests, because a
#          pair test needs both T1 lock files and so cannot run beside another worker
set -euo pipefail
cd "$(dirname "$0")/../../../../.."

variant=$1 shard=$2 out=$3
mkdir -p "$out"
mapfile -t paths < <(scripts/ci-shards.sh "$shard")

run() { # name, pytest arguments
    local name=$1 rc=0 start end
    shift
    start=$(date +%s.%N)
    uv run --frozen pytest -m "$MARK" --junitxml="$out/$variant-$name.xml" -p no:cacheprovider --durations=15 "$@" "${paths[@]}" || rc=$?
    end=$(date +%s.%N)
    printf '%s %s rc=%s seconds=%.1f\n' "$variant" "$name" "$rc" "$(echo "$end - $start" | bc)" | tee -a "$out/$variant.times"
    [ "$rc" -eq 0 ] || [ "$rc" -eq 5 ] || status=$rc
}

status=0
case $variant in
    n0) MARK="integration" run all -n0 ;;
    n2) MARK="integration" run all -n 2 --dist worksteal ;;
    n2split)
        MARK="integration and not pair" run nonpair -n 2 --dist worksteal
        MARK="integration and pair" run pair -n0
        ;;
    *) echo "error: no variant $variant" >&2; exit 2 ;;
esac
exit "$status"
