#!/usr/bin/env bash
# Self-test for ci-shards.sh: every package, deploy/ and scripts/ is tested by exactly one shard, a package that no
# shard names lands in the last one, --suggest balances measured durations, and a malformed shard list fails.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
shards="$here/ci-shards.sh"
cd "$here/.."

pass=0
ok() { echo "ok   $*"; pass=$((pass + 1)); }
fail() { echo "FAIL $*"; exit 1; }

# How many shards select a path: the ones that name it, plus the last one unless it ignores it.
# grep reads the whole list: grep -q exits at the first match, and pipefail turns the writer's SIGPIPE into a miss.
selected_by() {
    local path=$1 n=0 name last
    read -ra names <<<"$("$shards" | tr -d '[]"' | tr , ' ')"
    last=${names[-1]}
    for name in "${names[@]}"; do
        if [ "$name" = "$last" ]; then
            "$shards" "$name" | grep -xF -- "--ignore=$path" >/dev/null || n=$((n + 1))
        else
            "$shards" "$name" | grep -xF -- "$path" >/dev/null && n=$((n + 1))
        fi
    done
    echo "$n"
}

covers_tree() {
    local path n
    for path in packages/*/ deploy/ scripts/; do
        path=${path%/}
        n=$(selected_by "$path")
        [ "$n" -eq 1 ] || fail "$path is selected by $n shards"
    done
}

covers_tree
ok "the shard list tests every package, deploy/ and scripts/ exactly once"

export CI_SHARDS=$'a: broker\nb: workflow scripts/\nrest:'
covers_tree
[ "$(selected_by packages/admission)" -eq 1 ] || fail "admission, named by no shard, is not run"
"$shards" rest | grep -xF -- --ignore=packages/admission >/dev/null && fail "rest ignores admission, which no shard names"
ok "a package no shard names runs in the last shard"

[ "$("$shards")" = '["a","b","rest"]' ] || fail "names: got $("$shards")"
[ "$("$shards" b)" = $'packages/workflow\nscripts' ] || fail "shard b: got $("$shards" b)"
[ "$("$shards" rest)" = $'--ignore=packages/broker\n--ignore=packages/workflow\n--ignore=scripts' ] ||
    fail "shard rest: got $("$shards" rest)"
ok "names and arguments"

# A unit report whose per-test times add up to twice its wall time, as under xdist, and a serial integration report.
junit=$(mktemp -d)
trap 'rm -rf "$junit"' EXIT
report() {
    local file=$1 wall=$2 cases=""
    shift 2
    for case in "$@"; do cases+="<testcase classname=\"${case%=*}.tests.test_x\" name=\"t\" time=\"${case#*=}\"/>"; done
    echo "<testsuites><testsuite name=\"pytest\" time=\"$wall\">$cases</testsuite></testsuites>" >"$junit/$file"
}
report unit.xml 15 packages.workflow=20 packages.acceptance=10 packages.nosuchpackage=5
report integration.xml 100 packages.broker=60 packages.broker=40 packages.admission=50 packages.workflow=50 scripts=1
CI_SHARDS=$'a: broker\nb: workflow\nrest:'
layout=$("$shards" --suggest "$junit" 2>"$junit/err")
[ "$layout" = $'a: broker\nb: workflow\nrest:' ] || fail "layout: got $layout"
grep -q '^predicted seconds: slowest 50, mean 38, ratio 1.' "$junit/err" || fail "prediction: got $(cat "$junit/err")"
grep -q 'rest also runs acceptance admission scripts/$' "$junit/err" || fail "rest paths: got $(cat "$junit/err")"
"$shards" --suggest "$junit/nothing" >/dev/null 2>&1 && fail "--suggest accepted a missing directory"
ok "--suggest balances measured durations over the shard names"

rejects() {
    local why=$1 rc=0
    shift
    CI_SHARDS=$1 "$shards" "${@:2}" >/dev/null 2>&1 || rc=$?
    [ "$rc" -ne 0 ] || fail "accepted $why"
    ok "rejects $why"
}
rejects "a package in two shards" $'a: broker\nb: broker\nrest:'
rejects "a package that does not exist" $'a: nosuchpackage\nrest:'
rejects "a last shard that names a path" $'a: broker\nrest: workflow'
rejects "an unknown shard" $'a: broker\nrest:' nosuchshard
echo "$pass cases passed"
