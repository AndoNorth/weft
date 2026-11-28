#!/usr/bin/env bash
# Usage: release.sh X.Y.Z [--publish]
# Without --publish: checks the release preconditions, then writes the notes to release-X.Y.Z.md and prints them.
# With --publish: repeats the checks, then creates, verifies and pushes the signed tag and creates the GitHub Release.
# A tag is never moved or deleted, so a publish that stopped half way is resumed by running it again.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

die() { echo "release: refused: $*" >&2; exit 1; }

publish=0
version=
for arg in "$@"; do
    case $arg in
        --publish) publish=1 ;;
        -*) die "unknown flag $arg (usage: release.sh X.Y.Z [--publish])" ;;
        *) [ -z "$version" ] || die "more than one version given"; version=$arg ;;
    esac
done
[ -n "$version" ] || die "usage: release.sh X.Y.Z [--publish]"
[[ $version =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || die "$version is not a plain MAJOR.MINOR.PATCH version"
patch=${BASH_REMATCH[3]}
tag=v$version
notes=release-$version.md
allowed_signers=.github/allowed_signers

repo=${DSY_RELEASE_REPO:-}
if [ -z "$repo" ]; then
    url=$(git remote get-url origin)
    repo=$(sed -E 's#^(git@github\.com:|https://github\.com/)([^/]+/[^/]+)$#\2#; s#\.git$##' <<<"$url")
    [[ $repo =~ ^[^/]+/[^/]+$ ]] || die "cannot read the GitHub repository from the origin remote $url"
fi

# Prints "remote" when the tag is on origin, nothing when it is not, and dies when origin cannot be read.
remote_tag_commit() {
    local refs
    refs=$(git ls-remote origin "refs/tags/$tag" "refs/tags/$tag^{}") || die "cannot read tags from origin"
    awk -v peeled="refs/tags/$tag^{}" -v plain="refs/tags/$tag" '$2 == peeled { p = $1 } $2 == plain { t = $1 } END { print (p ? p : t) }' <<<"$refs"
}

# The previous release is the highest v* tag other than the one being made, so a resumed publish still sees the range.
range_check() {
    python3 - "$tag" <<'PY'
import sys

sys.path.insert(0, "scripts")
import release_notes as rn

target = sys.argv[1]
tags = [t for t in rn.run_git(["tag", "--list", "v*"]).splitlines() if rn.TAG_RE.fullmatch(t) and t != target]
start = max(tags, key=lambda t: tuple(int(n) for n in rn.TAG_RE.fullmatch(t).groups())) if tags else None
head = rn.run_git(["rev-parse", "HEAD"])
breaking = [s for _, _, s in rn.commits(start, head) if rn.parse(s).breaking]
changed = [name for name, _, _ in rn.contract_changes(start, head)]
for subject in breaking:
    print(f"breaking subject: {subject}")
for name in changed:
    print(f"contract version changed: contracts/{name}/VERSION")
PY
}

gate_check() {
    local sha=$1 ids id conclusions
    ids=$(gh api "repos/$repo/actions/workflows/ci.yml/runs?head_sha=$sha&event=push&per_page=100" --jq '.workflow_runs[].id') \
        || die "cannot read the ci workflow runs from GitHub"
    conclusions=
    for id in $ids; do
        conclusions+=$(gh api "repos/$repo/actions/runs/$id/jobs?per_page=100" --jq '.jobs[] | select(.name == "check") | .conclusion') \
            || die "cannot read the ci jobs from GitHub"
        conclusions+=$'\n'
    done
    grep -qx success <<<"$conclusions" || die "gate 1: the ci check job has no success on the push of $sha to main (found: $(tr '\n' ' ' <<<"$conclusions"))"
    conclusions=$(gh api "repos/$repo/actions/workflows/kind-smoke.yml/runs?head_sha=$sha&event=push&per_page=100" --jq '.workflow_runs[].conclusion') \
        || die "cannot read the kind-smoke workflow runs from GitHub"
    grep -qx success <<<"$conclusions" || die "gate 2: the kind-smoke workflow has no success on the push of $sha to main (found: $(tr '\n' ' ' <<<"$conclusions"))"
}

release_exists() {
    local out
    out=$(gh release view "$tag" --repo "$repo" --json tagName 2>&1) && return 0
    grep -qi 'not found' <<<"$out" && return 1
    die "cannot read the GitHub Release $tag: $out"
}

checks() {
    [ -z "$(git status --porcelain)" ] || die "the working tree is not clean"
    git fetch --quiet --tags origin main || die "cannot fetch origin main and its tags"
    local head
    head=$(git rev-parse HEAD)
    [ "$head" = "$(git rev-parse origin/main)" ] || die "HEAD is not origin/main (behind, ahead or diverged)"
    local root_version
    root_version=$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')
    [ "$root_version" = "$version" ] || die "$version differs from the root pyproject.toml version $root_version"
    uv lock --check >/dev/null || die "uv lock --check failed: run uv lock"
    ! release_exists || die "the GitHub Release $tag already exists"
    gate_check "$head"
    if [ "$patch" -gt 0 ]; then
        local found
        found=$(range_check)
        [ -z "$found" ] || die "a PATCH release cannot ship these, release a MINOR version instead:"$'\n'"$found"
    fi
}

verify_local() {
    git -c gpg.format=ssh -c "gpg.ssh.allowedSignersFile=$allowed_signers" verify-tag "$tag" >/dev/null 2>&1 \
        || die "the tag $tag has no valid signature from a key in $allowed_signers"
}

verify_github() {
    local sha verified
    sha=$(gh api "repos/$repo/git/ref/tags/$tag" --jq '.object.sha') || die "GitHub does not list the tag $tag"
    verified=$(gh api "repos/$repo/git/tags/$sha" --jq '.verification.verified') || die "cannot read the tag $tag from GitHub"
    [ "$verified" = true ] || die "GitHub does not report the tag $tag as verified: add the signing key to the GitHub account"
}

if [ "$publish" = 0 ]; then
    checks
    # checks fetches the remote tags, so a tag made elsewhere is seen here.
    ! git rev-parse --verify --quiet "refs/tags/$tag" >/dev/null || die "the tag $tag exists: run with --publish to resume it"
    python3 scripts/release_notes.py HEAD >"$notes"
    cat "$notes"
    echo "release: wrote $notes - add the gate evidence and the summary, then run: just release $version --publish" >&2
    exit 0
fi

checks
head=$(git rev-parse HEAD)
[ -f "$notes" ] || die "$notes does not exist: run the dry run first"
[ "$(head -n 1 "$notes")" = "$head" ] || die "HEAD $head is not the commit on the first line of $notes: run the dry run again"

local_commit=$(git rev-parse --verify --quiet "refs/tags/$tag^{commit}" || true)
remote_commit=$(remote_tag_commit)
[ -z "$local_commit" ] || [ "$local_commit" = "$head" ] || die "the tag $tag exists on $local_commit, not on HEAD"
[ -z "$remote_commit" ] || [ "$remote_commit" = "$head" ] || die "the tag $tag exists on origin at $remote_commit, not on HEAD"
if [ -z "$local_commit" ]; then
    git -c gpg.format=ssh tag -s -a "$tag" -m "$tag" HEAD
fi
verify_local
[ -n "$remote_commit" ] || git push origin "refs/tags/$tag"
verify_github

body=$(mktemp)
trap 'rm -f "$body"' EXIT
sed 1d "$notes" >"$body"
gh release create "$tag" --repo "$repo" --verify-tag --title "$tag" --notes-file "$body"
echo "release: published $tag"
