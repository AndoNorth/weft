#!/usr/bin/env bash
# Self-test for check-dev-ports.sh: a free port passes, a held port fails naming its holder, the DSY_SLOT stride moves
# a range, ss alone finds a holder, a dsy-* container is labelled a leftover, and a host without lsof and ss passes
# with a hint. Every port is one the test binds itself, on a free port it picked.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
check="$here/check-dev-ports.sh"
work=$(mktemp -d)
holder=
trap '[ -z "$holder" ] || kill "$holder" 2>/dev/null || true; rm -rf "$work"' EXIT

pass=0
ok() { echo "ok   $*"; pass=$((pass + 1)); }
fail() { echo "FAIL $*"; exit 1; }

free_port() { python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }

port=$(free_port)
no_hosts="$work/hosts.yaml"
echo 'ports: []' >"$no_hosts"
export DSY_HOST_PORTS="$no_hosts" DSY_PORT_MAP="$work/map"
echo "demo $port $port" >"$DSY_PORT_MAP"

# run <args to env...> leaves the output in $out and the exit code in $rc.
run() {
    rc=0
    out=$(env "$@" "$check" 2>&1) || rc=$?
}

run
[ "$rc" -eq 0 ] || fail "a free port failed: $out"
grep -qF "every port is free" <<<"$out" || fail "a free port gave no all-clear: $out"
ok "a free port passes"

python3 -m http.server "$port" --bind 127.0.0.1 >/dev/null 2>&1 &
holder=$!
for _ in $(seq 50); do ss -ltnH "sport = :$port" | grep -q . && break; sleep 0.1; done

run
[ "$rc" -eq 1 ] || fail "a held port exited $rc: $out"
grep -qF "held: demo port $port, pid $holder started" <<<"$out" || fail "the holder is not named: $out"
grep -qF "http.server $port" <<<"$out" || fail "the holder command is not shown: $out"
ok "a held port fails naming the pid, start time and command"

run DSY_PORT_TOOL=ss
[ "$rc" -eq 1 ] || fail "ss exited $rc: $out"
grep -qF "pid $holder" <<<"$out" || fail "ss did not find the holder: $out"
ok "ss alone finds the holder"

run DSY_PORT_TOOL=none
[ "$rc" -eq 0 ] || fail "no tool exited $rc: $out"
grep -qF "neither lsof nor ss" <<<"$out" || fail "no install hint: $out"
ok "no tool exits 0 with an install hint"

echo "demo $((port - 10)) $((port - 10)) 10" >"$DSY_PORT_MAP"
run DSY_SLOT=1
[ "$rc" -eq 1 ] || fail "slot 1 did not reach the held port: $out"
run DSY_SLOT=0
[ "$rc" -eq 0 ] || fail "slot 0 reached a port outside its range: $out"
ok "DSY_SLOT shifts a range by its stride"

echo "demo $port $port" >"$DSY_PORT_MAP"
mkdir "$work/bin"
printf '#!/bin/sh\necho dsy-leftover\n' >"$work/bin/docker"
chmod +x "$work/bin/docker"
run PATH="$work/bin:$PATH"
grep -qF "remove it with: docker rm -f -v dsy-leftover" <<<"$out" || fail "a dsy-* container is not labelled: $out"
[ "$rc" -eq 1 ] || fail "a leftover container did not fail the check: $out"
printf '#!/bin/sh\necho other-service\n' >"$work/bin/docker"
run PATH="$work/bin:$PATH"
grep -qF "leftover" <<<"$out" && fail "a container that is not dsy-* was called a leftover: $out"
ok "only a dsy-* container is labelled a leftover"

kill "$holder"
wait "$holder" 2>/dev/null || true
holder=
run
[ "$rc" -eq 0 ] || fail "the port stayed held after its holder stopped: $out"
ok "a port passes again once its holder stops"
echo "$pass cases passed"
