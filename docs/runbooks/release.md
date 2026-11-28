# Release

For the person who cuts a release with `just release`.
Nothing is tagged when a PR merges.
Merging the version bump only sets the number in `pyproject.toml`.
Tagging and publishing is a person's step, done by running `just release X.Y.Z --publish`.
The design and its reasons are in [the release process](../delivery/release-process.md).

## One-time setup

Do these once, in order.

1. Register the public key on GitHub as a signing key, which is separate from an authentication key:
   `gh ssh-key add ~/.ssh/<key>.pub --type signing --title "release signing"`
2. Tell git to sign with SSH and that key:
   `git config --global gpg.format ssh` and `git config --global user.signingkey ~/.ssh/<key>.pub`
3. Add one line to `.github/allowed_signers`, in the form `captain <key type> <key>`, through a normal PR.
   The file holds the public key only.
   Keep old lines after a key change so old tags still verify.
4. Create a repository ruleset on `refs/tags/v*` that blocks creation, update and deletion for everyone except the repository admin.
5. Create a ruleset on `main` that requires the `pr-title` check to pass before merge.

## Per release

1. Open a PR titled `chore(release): X.Y.Z` that sets the version in the root `pyproject.toml` and reruns `uv lock`, and nothing else.
   Squash merge it.
2. On a clean checkout, run the dry run: `just release X.Y.Z`.
   It writes the notes to `release-X.Y.Z.md` and prints them.
   The file is not committed.
3. Run the gate checks that CI does not run, on that commit, and paste their output under `## Gate` in `release-X.Y.Z.md`.
   They are listed under "Release gate" in [the release process](../delivery/release-process.md#release-gate).
4. Replace the `<!-- Write the release summary here. -->` line under `## Summary` in `release-X.Y.Z.md`.
   Leave the first line, the commit sha, alone.
5. Publish: `just release X.Y.Z --publish`.
   It repeats the checks, creates the signed tag, verifies it locally, pushes it, checks that GitHub reports it as verified, and creates the GitHub Release.
6. Open the Release page for `vX.Y.Z`.
   Check the tag shows Verified, the notes match the file, and the release is marked Latest.

If `--publish` stops half way, run it again.
It resumes from the tag that is already there.
A tag is never moved or deleted.

## Refusals

Every refusal prints `release: refused: <reason>` and exits 1.

| Refusal | Meaning and fix |
| --- | --- |
| `unknown flag <arg>`, `more than one version given`, `usage: release.sh X.Y.Z [--publish]` | Wrong arguments. The only flag is `--publish`, with one version. |
| `<X.Y.Z> is not a plain MAJOR.MINOR.PATCH version` | Pass digits only, such as `0.1.0`. No `v` prefix, no suffix. |
| `cannot read the GitHub repository from the origin remote` | `origin` is not a GitHub URL. Fix the remote. |
| `cannot read tags from origin`, `cannot fetch origin main and its tags` | Network or credentials. Fix and run again. |
| `the working tree is not clean` | Commit or discard local changes. |
| `HEAD is not origin/main (behind, ahead or diverged)` | Check out `main` and pull until `HEAD` equals `origin/main`. |
| `<X.Y.Z> differs from the root pyproject.toml version <v>` | The version bump PR is missing, not merged, or has a different number. |
| `uv lock --check failed: run uv lock` | Run `uv lock` in a fix PR and merge it. |
| `the GitHub Release vX.Y.Z already exists` | That version is published. Pick the next version. |
| `gate 1: the ci check job has no success on the push of <sha> to main` | CI did not pass, or did not run, on that commit. Fix through PRs and release from the later commit. A skipped run does not count. |
| `gate 2: the kind-smoke workflow has no success on the push of <sha> to main` | Same, for `kind-smoke`. |
| `cannot read the ci workflow runs`, `cannot read the ci jobs`, `cannot read the kind-smoke workflow runs`, `cannot read the GitHub Release vX.Y.Z` | `gh` cannot reach GitHub. Run `gh auth status` and try again. |
| `a PATCH release cannot ship these, release a MINOR version instead:` | The range holds a `!` subject or a changed `contracts/*/VERSION`. Release a MINOR version. |
| `the tag vX.Y.Z exists: run with --publish to resume it` | Dry run only. A tag is already there. Run with `--publish` to resume. |
| `release-X.Y.Z.md does not exist: run the dry run first` | Run `just release X.Y.Z` first. |
| `HEAD <sha> is not the commit on the first line of release-X.Y.Z.md: run the dry run again` | `main` moved since the dry run. Run the dry run again and redo the gate evidence and summary. |
| `the tag vX.Y.Z exists on <sha>, not on HEAD` | The tag is on another commit locally. It is never moved. Release the next version. |
| `the tag vX.Y.Z exists on origin at <sha>, not on HEAD` | Same, on `origin`. |
| `the tag vX.Y.Z has no valid signature from a key in .github/allowed_signers` | The key is not in that file, or git is not signing with it. Check setup steps 2 and 3. |
| `GitHub does not list the tag vX.Y.Z`, `cannot read the tag vX.Y.Z from GitHub` | The push did not land, or `gh` cannot read it. Run `--publish` again. |
| `GitHub does not report the tag vX.Y.Z as verified: add the signing key to the GitHub account` | Setup step 1 is missing. Register the key as a signing key, then run `--publish` again. |

## Withdraw a bad release

A published tag is never moved or deleted.

1. Fix forward with a PATCH release, such as `0.1.1`, through the steps above.
2. Edit the bad release with `gh release edit vX.Y.Z`.
   Prefix its title with `[withdrawn]` and start its notes with one line saying what is wrong and which version replaces it.
3. On the Release page, check the new release is marked Latest.
