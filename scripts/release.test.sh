#!/usr/bin/env bash
# Self-test for release.sh, run in a scratch clone with a local bare remote, a fake gh and uv, and throwaway SSH keys.
# Every refusal leaves no tag and no Release behind, and the publish path creates a signed tag on a throwaway version.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(dirname "$here")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# Isolate git from the machine's configuration and signing setup.
export HOME="$work/home" GIT_CONFIG_GLOBAL="$work/gitconfig" GIT_CONFIG_NOSYSTEM=1
mkdir -p "$HOME"
git config --global user.name tester
git config --global user.email tester@example.com
git config --global init.defaultBranch main
git config --global commit.gpgsign false

ssh-keygen -q -t ed25519 -N '' -C captain -f "$work/captain"
ssh-keygen -q -t ed25519 -N '' -C stranger -f "$work/stranger"
git config --global user.signingkey "$work/captain.pub"

# Fakes for the two tools that would reach the network or the real project.
fake="$work/bin"
mkdir -p "$fake"
export FAKE_STATE="$work/state"
mkdir -p "$FAKE_STATE"
cat >"$fake/gh" <<'F'
#!/usr/bin/env bash
echo "gh $*" >>"$FAKE_STATE/gh.log"
case "$1 $2" in
    "release view")
        if grep -qx "$3" "$FAKE_STATE/releases" 2>/dev/null; then exit 0; fi
        echo "release not found" >&2; exit 1 ;;
    "release create")
        echo "$3" >>"$FAKE_STATE/releases"
        while [ $# -gt 0 ]; do [ "$1" != --notes-file ] || cp "$2" "$FAKE_STATE/notes-body"; shift; done ;;
    "api repos/"*) ;;
esac
if [ "$1" = api ]; then
    case "$2" in
        */workflows/ci.yml/runs*) echo 101 ;;
        */actions/runs/*/jobs*) echo "${FAKE_CI:-success}" ;;
        */workflows/kind-smoke.yml/runs*) echo "${FAKE_SMOKE:-success}" ;;
        */git/ref/tags/*) echo 0123456789abcdef ;;
        */git/tags/*) echo "${FAKE_VERIFIED:-true}" ;;
    esac
fi
exit 0
F
cat >"$fake/uv" <<'F'
#!/usr/bin/env bash
[ "${FAKE_LOCK:-ok}" = ok ] || { echo "lock is stale" >&2; exit 1; }
F
chmod +x "$fake/gh" "$fake/uv"
export PATH="$fake:$PATH" DSY_RELEASE_REPO=owner/repo

pass=0
ok() { echo "ok   $*"; pass=$((pass + 1)); }
fail() { echo "FAIL $*"; exit 1; }

# Builds the scratch clone: a bare origin holding main at version 0.1.0 with the release files, then a clone of it.
fresh() {
    rm -rf "$work/origin.git" "$work/seed" "$work/clone" "${FAKE_STATE:?}"/*
    git init -q --bare "$work/origin.git"
    git init -q "$work/seed"
    (
        cd "$work/seed"
        mkdir -p scripts .github contracts/events
        cp "$repo_root/scripts/release.sh" "$repo_root/scripts/release_notes.py" scripts/
        echo 'release-*.md' >.gitignore
        printf '[project]\nname = "demo"\nversion = "0.1.0"\n' >pyproject.toml
        echo 5 >contracts/events/VERSION
        echo "captain $(cut -d' ' -f1,2 "$work/captain.pub")" >.github/allowed_signers
        git add -A
        git commit -q -m 'chore(demo): [#1] seed the repository'
        git remote add origin "$work/origin.git"
        git push -q origin main
    )
    git clone -q "$work/origin.git" "$work/clone"
}

# A commit on main, pushed, so a later release has a range.
land() {
    (
        cd "$work/clone"
        echo "$RANDOM" >>"change.txt"
        git add -A
        git commit -q -m "$1"
        git push -q origin main
    )
}

# run <args> leaves the output in $out and the exit code in $rc.
run() {
    rc=0
    out=$(cd "$work/clone" && scripts/release.sh "$@" 2>&1) || rc=$?
}

# is <rc> <pattern> holds when the last run exited with rc and printed the pattern.
is() { [ "$rc" = "$1" ] && grep -q -- "$2" <<<"$out"; }

refuses() {
    local name=$1 want=$2
    is 1 "$want" || fail "$name: rc=$rc out='$out'"
    [ ! -e "$FAKE_STATE/releases" ] || fail "$name: a Release was created"
    [ -z "$(git -C "$work/clone" tag)" ] || fail "$name: a tag was created"
    ok "$name"
}

# Dry run

fresh; run 0.1.0
is 0 'seed the repository' || fail "dry-run: rc=$rc out='$out'"
[ "$(head -n 1 "$work/clone/release-0.1.0.md")" = "$(git -C "$work/clone" rev-parse HEAD)" ] || fail "dry-run: the notes do not start with the sha"
[ -z "$(git -C "$work/clone" status --porcelain)" ] || fail "dry-run: the notes file is not ignored"
ok dry-run-writes-and-prints-the-notes

fresh; run 0.1
refuses malformed-version 'not a plain MAJOR.MINOR.PATCH'
fresh; run 0.1.0-rc.1
refuses prerelease-version 'not a plain MAJOR.MINOR.PATCH'
fresh; run
refuses missing-version 'usage'

fresh; echo x >"$work/clone/dirty.txt"; run 0.1.0
refuses dirty-tree 'working tree is not clean'

fresh; land 'fix(demo): [#2] move main on'; git -C "$work/clone" reset -q --hard HEAD~1; run 0.1.0
refuses head-behind-origin-main 'HEAD is not origin/main'
fresh; (cd "$work/clone" && git commit -q --allow-empty -m 'fix(demo): [#2] local only'); run 0.1.0
refuses head-ahead-of-origin-main 'HEAD is not origin/main'

fresh; run 0.2.0
refuses version-mismatch 'differs from the root pyproject.toml version 0.1.0'

fresh; FAKE_LOCK=stale run 0.1.0
refuses stale-lock 'uv lock --check failed'

fresh; echo v0.1.0 >"$FAKE_STATE/releases"; run 0.1.0
is 1 'Release v0.1.0 already exists' || fail "existing-release: rc=$rc out='$out'"
ok existing-release

fresh; FAKE_CI=failure run 0.1.0
refuses gate-ci-failed 'gate 1'
fresh; FAKE_CI=skipped run 0.1.0
refuses gate-ci-skipped 'gate 1'
fresh; FAKE_SMOKE=failure run 0.1.0
refuses gate-kind-smoke-failed 'gate 2'

# PATCH guard

patch_fixture() {
    fresh
    git -C "$work/clone" -c gpg.format=ssh tag -s -a v0.1.0 -m v0.1.0 HEAD
    git -C "$work/clone" push -q origin v0.1.0
}
bump() { (cd "$work/clone" && sed -i "s/^version = .*/version = \"$1\"/" pyproject.toml && git commit -qam 'chore(release): [#3] bump' && git push -q origin main); }

patch_fixture; land 'fix(demo): [#4] a plain fix'; bump 0.1.1; run 0.1.1
[ "$rc" = 0 ] || fail "patch-with-fixes-only: rc=$rc out='$out'"
ok patch-release-with-fixes-only

patch_fixture; land 'feat(api)!: [#5] drop the v0 route'; bump 0.1.1; run 0.1.1
is 1 'breaking subject: feat(api)!' || fail "patch-breaking: rc=$rc out='$out'"
[ ! -e "$work/clone/release-0.1.1.md" ] || fail "patch-breaking: notes were written"
ok patch-refuses-a-breaking-subject

patch_fixture
(cd "$work/clone" && echo 6 >contracts/events/VERSION && git commit -qam 'feat(events): [#6] bump the events contract' && git push -q origin main)
bump 0.1.1; run 0.1.1
is 1 'contract version changed: contracts/events/VERSION' || fail "patch-contract: rc=$rc out='$out'"
ok patch-refuses-a-changed-contract-version

patch_fixture
(cd "$work/clone" && echo 6 >contracts/events/VERSION && git commit -qam 'feat(events): [#6] bump the events contract' && git push -q origin main)
bump 0.2.0; run 0.2.0
[ "$rc" = 0 ] || fail "minor-with-contract-change: rc=$rc out='$out'"
ok minor-release-may-change-a-contract

# Publish

dry() { fresh; run 0.1.0; [ "$rc" = 0 ] || fail "setup dry run: $out"; }

fresh; run 0.1.0 --publish
refuses publish-without-notes 'release-0.1.0.md does not exist'

dry; land 'fix(demo): [#7] a later commit'; run 0.1.0 --publish
refuses publish-notes-sha-mismatch 'is not the commit on the first line of release-0.1.0.md'

dry; FAKE_VERIFIED=false run 0.1.0 --publish
is 1 'does not report the tag v0.1.0 as verified' || fail "github-unverified: rc=$rc out='$out'"
[ ! -e "$FAKE_STATE/releases" ] || fail "github-unverified: a Release was created"
ok publish-refuses-when-github-does-not-verify-the-tag

dry; git -C "$work/clone" tag -a v0.1.0 -m v0.1.0 HEAD; run 0.1.0 --publish
is 1 'no valid signature' || fail "unsigned-tag: rc=$rc out='$out'"
[ ! -e "$FAKE_STATE/releases" ] || fail "unsigned-tag: a Release was created"
[ -z "$(git -C "$work/clone" ls-remote origin refs/tags/v0.1.0)" ] || fail "unsigned-tag: the tag was pushed"
ok publish-refuses-an-unsigned-tag

dry; git -C "$work/clone" -c gpg.format=ssh -c "user.signingkey=$work/stranger.pub" tag -s -a v0.1.0 -m v0.1.0 HEAD; run 0.1.0 --publish
is 1 'no valid signature' || fail "wrong-signer: rc=$rc out='$out'"
[ ! -e "$FAKE_STATE/releases" ] || fail "wrong-signer: a Release was created"
[ -z "$(git -C "$work/clone" ls-remote origin refs/tags/v0.1.0)" ] || fail "wrong-signer: the tag was pushed"
ok publish-refuses-a-tag-signed-by-another-key

fresh; land 'fix(demo): [#7] a later commit'; run 0.1.0; git -C "$work/clone" -c gpg.format=ssh tag -s -a v0.1.0 -m v0.1.0 HEAD~1
run 0.1.0 --publish
is 1 'v0.1.0 exists on .*, not on HEAD' || fail "tag-on-other-commit: rc=$rc out='$out'"
ok publish-refuses-a-tag-on-another-commit

dry; run 0.1.0 --publish
tagged=$(git -C "$work/clone" rev-parse HEAD)
is 0 'published v0.1.0' || fail "publish: rc=$rc out='$out'"
[ "$(git -C "$work/origin.git" rev-parse 'refs/tags/v0.1.0^{commit}')" = "$tagged" ] || fail "publish: the remote tag is not on HEAD"
git -C "$work/clone" -c gpg.format=ssh -c "gpg.ssh.allowedSignersFile=$work/clone/.github/allowed_signers" verify-tag v0.1.0 >/dev/null 2>&1 || fail "publish: the tag does not verify"
grep -qx v0.1.0 "$FAKE_STATE/releases" || fail "publish: no Release created"
grep -q -- '--verify-tag' "$FAKE_STATE/gh.log" || fail "publish: --verify-tag missing"
[ "$(head -n 1 "$FAKE_STATE/notes-body")" != "$tagged" ] || fail "publish: the sha line was not stripped"
grep -q '## Summary' "$FAKE_STATE/notes-body" || fail "publish: the notes body is missing"
ok publish-creates-a-verified-tag-and-the-release

run 0.1.0 --publish
is 1 'already exists' || fail "publish-twice: rc=$rc out='$out'"
ok publish-refuses-once-the-release-exists

# Resume: the tag was created and verified locally, then the push failed.
dry; git -C "$work/clone" -c gpg.format=ssh tag -s -a v0.1.0 -m v0.1.0 HEAD; run 0.1.0 --publish
[ "$rc" = 0 ] || fail "resume-local-tag: rc=$rc out='$out'"
[ -n "$(git -C "$work/clone" ls-remote origin refs/tags/v0.1.0)" ] || fail "resume-local-tag: the tag was not pushed"
grep -qx v0.1.0 "$FAKE_STATE/releases" || fail "resume-local-tag: no Release created"
ok resume-pushes-an-existing-local-tag

# Resume: the tag is on the remote and the Release creation failed.
dry; git -C "$work/clone" -c gpg.format=ssh tag -s -a v0.1.0 -m v0.1.0 HEAD; git -C "$work/clone" push -q origin v0.1.0
before=$(git -C "$work/origin.git" rev-parse refs/tags/v0.1.0)
run 0.1.0 --publish
[ "$rc" = 0 ] || fail "resume-pushed-tag: rc=$rc out='$out'"
[ "$(git -C "$work/origin.git" rev-parse refs/tags/v0.1.0)" = "$before" ] || fail "resume-pushed-tag: the remote tag moved"
grep -qx v0.1.0 "$FAKE_STATE/releases" || fail "resume-pushed-tag: no Release created"
ok resume-creates-the-release-for-a-pushed-tag

dry; git -C "$work/clone" -c gpg.format=ssh tag -s -a v0.1.0 -m v0.1.0 HEAD; run 0.1.0
is 1 'run with --publish to resume' || fail "dry-run-with-tag: rc=$rc out='$out'"
ok dry-run-refuses-when-the-tag-exists

echo "$pass cases passed"
