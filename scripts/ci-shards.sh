#!/usr/bin/env bash
# Usage: ci-shards.sh [shard | --suggest <dir>]
# The test shards CI runs side by side, one runner each. Without an argument, prints the shard names as a JSON array
# for the workflow matrix. With a shard, prints the pytest arguments that select its tests, one per line.
# --suggest reads the JUnit files under <dir> (the junit-* artifacts of main runs, from gh run download) and prints a
# balanced layout for the same shard names, ready to paste over the list below, with the predicted seconds of each.
set -euo pipefail
cd "$(dirname "$0")/.."

# One shard per line: its name, then what it runs, where a word is a package under packages/ and a word ending in /
# is a top-level directory. The last shard names nothing and runs every path no other shard names, so a package
# missing from this list is still tested. Adding a line adds a runner.
shards=${CI_SHARDS:-"
workflow: workflow
admission: admission itest jobtools stateops temporal workloads
dispatchapi: artifactreaper compile dispatchapi events exampleflow keys placement servicekit
worker: deploy/ aggregate broker clusterkit eventstore jobcheck jobexamples jobpatch migrate
artifacts: compat jobdoc jobstate kernel obs plan runtime worker scripts/
rest:
"}

names=()
declare -A paths seen
while IFS= read -r line; do
    [ -n "$line" ] || continue
    name=${line%%:*}
    names+=("$name")
    paths[$name]=
    for word in ${line#*:}; do
        case $word in */) path=${word%/} ;; *) path=packages/$word ;; esac
        [ -e "$path" ] || { echo "error: shard $name names $path, which does not exist" >&2; exit 1; }
        [ -z "${seen[$path]:-}" ] || { echo "error: $path is in shards ${seen[$path]} and $name" >&2; exit 1; }
        seen[$path]=$name
        paths[$name]+="$path "
    done
done <<<"$shards"
last=${names[-1]}
[ -z "${paths[$last]}" ] || { echo "error: the last shard, $last, must name nothing" >&2; exit 1; }

if [ "${1:-}" = --suggest ]; then
    [ $# -eq 2 ] && [ -d "$2" ] || { echo "usage: ci-shards.sh --suggest <dir of JUnit files>" >&2; exit 2; }
    python3 -I - "$2" "${names[@]}" <<'PY'
import sys, glob, collections, os
import xml.etree.ElementTree as ET

root, names = sys.argv[1], sys.argv[2:]
files = glob.glob(os.path.join(root, "**", "*.xml"), recursive=True)
if not files:
    sys.exit(f"error: no JUnit files under {root}")

# A report's per-test times add up to CPU seconds under xdist, so each report is scaled to the wall seconds of its
# session, which is what a runner spends. A classname maps to the path a shard names.
weight = collections.Counter()
for f in files:
    suite = ET.parse(f).getroot().find("testsuite")
    parts = [(t.get("classname").split("."), float(t.get("time"))) for t in suite.iter("testcase")]
    total = sum(t for _, t in parts)
    if not total:
        continue
    for c, t in parts:
        weight["/".join(c[:2]) if c[0] == "packages" else c[0]] += t * float(suite.get("time")) / total

# Paths that no longer exist, and tests outside every path, have no place to be named: the last shard runs them.
named = {p: w for p, w in weight.items() if os.path.exists(p)}
loads = [0.0] * len(names)
loads[-1] = sum(weight.values()) - sum(named.values())
bins = [[] for _ in names]
# scripts/cluster tests read a running stack and are skipped only by the conftest of packages/obs, which pytest applies
# to the whole session, so the two must be selected by the same shard.
together = [("scripts", "packages/obs")]
units = {p: [p] for p in named}
for first, second in together:
    if first in units and second in units:
        units[first] += units.pop(second)
cost = {k: sum(named[p] for p in v) for k, v in units.items()}
# Longest first into the least loaded shard. The last shard names nothing, so the paths it receives are not printed.
for key, w in sorted(cost.items(), key=lambda kv: -kv[1]):
    i = loads.index(min(loads))
    loads[i] += w
    bins[i] += units[key]

def word(path):
    return path[len("packages/"):] if path.startswith("packages/") else path + "/"

# The layout goes to stdout so it pastes as is, the prediction to stderr.
mean = sum(loads) / len(loads)
err = lambda m: print(m, file=sys.stderr)
err(f"predicted seconds: slowest {max(loads):.0f}, mean {mean:.0f}, ratio {max(loads) / mean:.2f}")
for name, load, paths in zip(names, loads, bins):
    err(f"  {name}: {load:.0f} s" + (f", rest also runs {' '.join(word(p) for p in sorted(paths))}" if name == names[-1] else ""))
    print(f"{name}: " + " ".join(word(p) for p in sorted(paths)) if name != names[-1] else f"{name}:")
PY
    exit
fi
if [ $# -eq 0 ]; then
    json=$(printf ',"%s"' "${names[@]}")
    echo "[${json#,}]"
    exit
fi
[ -n "${paths[$1]+set}" ] || { echo "error: no shard $1, the shards are ${names[*]}" >&2; exit 2; }
if [ "$1" = "$last" ]; then
    for path in "${!seen[@]}"; do echo "--ignore=$path"; done | sort
else
    read -ra own <<<"${paths[$1]}"
    printf '%s\n' "${own[@]}"
fi
