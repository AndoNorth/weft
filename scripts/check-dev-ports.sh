#!/usr/bin/env bash
# Usage: check-dev-ports.sh
# Reports every host port a run is about to bind that something already listens on, with the holder's pid, start time
# and command, and a dsy-* container that publishes it as a leftover. Nothing is stopped or removed.
# Ports come from scripts/dev-ports.map and deploy/host/ports.yaml, and DSY_SLOT shifts the rows that have a stride.
# DSY_PORT_MAP and DSY_HOST_PORTS replace the two tables, DSY_PORT_TOOL (lsof, ss or none) limits the probes.
# Exit 0 every port free, or neither lsof nor ss installed, 1 a port is held.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

map=${DSY_PORT_MAP:-scripts/dev-ports.map}
host_ports=${DSY_HOST_PORTS:-deploy/host/ports.yaml}
slot=${DSY_SLOT:-0}

# lsof only sees the sockets of the user's own processes, so a port a root-owned docker-proxy holds needs ss as well.
tools=${DSY_PORT_TOOL:-}
if [ -z "$tools" ]; then
    tools=""
    for t in lsof ss; do command -v "$t" >/dev/null && tools+="$t "; done
    tools=${tools:-none}
fi
if [ "$tools" = none ]; then
    echo "check-dev-ports: neither lsof nor ss is installed, so no port was checked." >&2
    echo "  Debian or Ubuntu: sudo apt install lsof (or iproute2 for ss)" >&2
    exit 0
fi

# Prints "<port> <pid>" for each listener in the range, with pid ? when the tool cannot see the owner.
probe() {
    local tool=$1 lo=$2 hi=$3
    case "$tool" in
        lsof)
            lsof -iTCP:"$lo-$hi" -sTCP:LISTEN -P -n -Fpn 2>/dev/null |
                awk '/^p/ { pid = substr($0, 2) } /^n/ { n = split($0, a, ":"); print a[n], pid }' || true ;;
        ss)
            ss -ltnpH "( sport >= :$lo and sport <= :$hi )" 2>/dev/null |
                awk '{ n = split($4, a, ":"); pid = "?"; if (match($0, /pid=[0-9]+/)) pid = substr($0, RSTART + 4, RLENGTH - 4); print a[n], pid }' || true ;;
        *) echo "check-dev-ports: unknown DSY_PORT_TOOL $tool" >&2; exit 2 ;;
    esac
}

# One row per port, the one that names a pid first.
listeners() {
    local tool
    for tool in $tools; do probe "$tool" "$1" "$2"; done | sort -k1,1n -k2,2 | awk '!seen[$1]++'
}

describe() {
    local pid=$1
    if [ "$pid" = "?" ]; then echo "holder hidden, try sudo"; return; fi
    printf 'pid %s started %s: %s' "$pid" "$(ps -p "$pid" -o lstart= 2>/dev/null | tr -s ' ' | sed 's/^ //')" \
        "$(ps -p "$pid" -o args= 2>/dev/null | cut -c1-100 || true)"
}

# A published port is held by docker-proxy, so the container behind it names the real owner.
container_of() {
    command -v docker >/dev/null || return 0
    timeout 5 docker ps --filter "publish=$1" --format '{{.Names}}' 2>/dev/null | grep '^dsy-' | head -n 1 || true
}

held=0
check() {
    local name=$1 lo=$2 hi=$3 port pid box
    while read -r port pid; do
        [ -n "$port" ] || continue
        held=1
        box=$(container_of "$port")
        echo "held: $name port $port, $(describe "$pid")"
        [ -z "$box" ] || echo "  leftover dsy container $box, left running, remove it with: docker rm -f -v $box"
    done < <(listeners "$lo" "$hi")
}

while read -r name lo hi stride; do
    case "$name" in '' | '#'*) continue ;; esac
    check "$name" $((lo + slot * ${stride:-0})) $((hi + slot * ${stride:-0}))
done <"$map"

if [ -f "$host_ports" ]; then
    while read -r name port; do check "$name" "$port" "$port"; done < <(yq -r '.ports[] | .name + " " + (.host_port | tostring)' "$host_ports")
fi

[ "$held" -eq 0 ] || { echo "check-dev-ports: a port above is held, stop its holder or pick another DSY_SLOT" >&2; exit 1; }
echo "check-dev-ports: every port is free"
