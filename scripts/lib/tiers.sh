# Sourced by the scripts that run pytest. The test tiers, each a pytest marker expression.
# Every marker registered in pyproject.toml has a row here, which scripts/tiers.test.sh checks.
# The unit tier is the default run, so it leaves out the tiers that need containers, a cluster or a long wait.
# The isolated and cluster expressions name their marker on purpose: the fixtures that deselect those tests read the expression.

declare -A TIER_EXPR=(
    [unit]='not integration and not slow and not e2e'
    [integration]='integration'
    [e2e]='e2e'
    [seam]='seam'
    [pair]='pair'
    [isolated]='isolated'
    [cluster]='cluster'
    [slow]='slow'
)

# tier_args <tier>: sets tier_pytest_args to the pytest arguments of the tier, or exits the caller's check with 2.
tier_args() {
    local tier=$1
    if [ -z "${TIER_EXPR[$tier]:-}" ]; then
        echo "error: unknown tier '$tier', one of: $(printf '%s ' "${!TIER_EXPR[@]}")" >&2
        return 2
    fi
    # shellcheck disable=SC2034 # read by the sourcing script
    tier_pytest_args=(-m "${TIER_EXPR[$tier]}")
}
