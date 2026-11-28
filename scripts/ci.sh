#!/usr/bin/env bash
# Usage: ci.sh [--docs | --full | --checks | --shard <name>]
# The CI gate: the same command runs locally and in .github/workflows/ci.yml.
# The docs path skips the unit and integration tests, which no documentation file can affect.
# CI splits the full path in two: --checks runs it without the tests, and --shard runs only the unit and integration
# tests of one shard of scripts/ci-shards.sh, on a runner of its own.
# Without a flag, the docs path is taken when every file changed against the merge base with origin/main is documentation.
set -euo pipefail
cd "$(dirname "$0")/.."

# Committed, uncommitted and untracked changes since the merge base, or nothing when there is no origin/main.
changed() {
    local base
    base=$(git merge-base origin/main HEAD 2>/dev/null) || return 0
    git diff --name-only --no-renames "$base"
    git ls-files --others --exclude-standard
}

case "${1:-}" in
    --docs) mode=docs ;;
    --full) mode=full ;;
    --checks) mode=checks ;;
    --shard)
        [ $# -eq 2 ] || { echo "usage: ci.sh --shard <name>" >&2; exit 2; }
        out=$(scripts/ci-shards.sh "$2")
        mapfile -t args <<<"$out"
        [ -n "${args[0]}" ] || args=()
        echo "== ci shard: $2"
        # The reports go under .pytest_cache, which git already ignores, one file per pytest call.
        report=".pytest_cache/junit-$2"
        scripts/test.sh --junitxml="$report-unit.xml" --durations=30 "${args[@]}"
        scripts/itest.sh -- --junitxml="$report-integration.xml" --durations=30 "${args[@]}"
        exit ;;
    "") mode=$(changed | scripts/ci-paths.sh) ;;
    *) echo "usage: ci.sh [--docs | --full | --checks | --shard <name>]" >&2; exit 2 ;;
esac
echo "== ci path: $mode"

scripts/lint.sh
scripts/check-links.sh
echo "== contracts-map"
scripts/check-contracts-map.sh
scripts/check-contracts-map.test.sh
echo "== ci-paths"
scripts/ci-paths.test.sh
echo "== ci-shards"
scripts/ci-shards.test.sh
echo "== doctor"
scripts/doctor.test.sh
echo "== check-dev-ports"
scripts/check-dev-ports.test.sh
echo "== release"
scripts/release.test.sh
echo "== verify-lint"
scripts/lint.sh --verify-skills
if [ "$mode" = full ]; then
    scripts/test.sh
    scripts/itest.sh
fi
# checks.pre-commit reads every tracked file, documentation included, so the flake check stays on both paths.
nix flake check
