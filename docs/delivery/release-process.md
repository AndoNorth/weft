---
status: draft
date: 2026-11-20
updated: 2026-11-20
issues: [583]
scope: [release, delivery, ci]
---

# Tagging and release process

## Problem

The project has no tags, no releases and no written rule for making one.
`pyproject.toml:3` and all 33 workspace packages say `version = "0.0.0"`, and nothing reads that number.
When the proof of concept is done there is no agreed way to say "this commit is the result", to name it, to prove it passed the gates, or to tell a reader what changed since the last one.
Without a rule, the first release would be improvised, and every later one would copy whatever the improvisation happened to be.

## Goals

- A reader can tell from a version number alone whether an upgrade may break them, using the rules in "Compatibility below 1.0.0".
- Every release is one SSH-signed, annotated git tag `vX.Y.Z` on a commit of `main`, and one GitHub Release on that tag.
- A release cannot be published when its tag's signature does not verify, locally and on GitHub.
- The version is written in exactly one file, the root `pyproject.toml`, and a release cannot be published when that file and the tag disagree.
- A release is published only when the gate in "Release gate" passed on the tagged commit, and the release notes carry the evidence.
- Release notes are generated from the squash-merge commit subjects, grouped by type, with breaking changes and then contract version changes at the top.
- A bad release is never deleted or moved, and the withdrawal steps leave a reader pointed at the fix.
- Releasing is one recipe the captain runs, after a dry run that writes the notes to a file and prints them.

## Non-Goals

- Versioning each package, image or contract separately for release purposes.
- Long-lived release branches, backports, or support for more than the latest release.
- Alpha, beta or release candidate tags.
- Wheels on a package index, a documentation site, a software bill of materials or build provenance.

## Versioning in five minutes

This section is for a reader designing a release process for the first time.

A version is three numbers, `MAJOR.MINOR.PATCH`, defined by Semantic Versioning 2.0.0 (SemVer).
Once a project is at 1.0.0 or above, the rule is simple.
PATCH goes up for fixes that change nothing a user relies on.
MINOR goes up for new things that do not break existing users.
MAJOR goes up when something an existing user relies on breaks.
Each bump resets the numbers to its right to zero, so after 1.4.2 a new feature gives 1.5.0, not 1.5.2.

Below 1.0.0 the rule is looser on purpose.
SemVer says that 0.y.z is initial development and anything may change at any time.
Most projects then shift the rule one place to the right: MINOR (the y in 0.y.z) means "may break", and PATCH means "fixes only".
This spec adopts that convention.
A version starting 0.0 says even less: by convention 0.0.x means "nothing settled yet, any release may break anything", which is why this project starts at 0.1.0 and not 0.0.1.

A pre-release is a version with a hyphen and a label after it, such as `0.1.0-rc.1`, `0.1.0-beta.2` or `0.1.0-alpha.1`.
It means "a candidate for 0.1.0, not 0.1.0 itself".
Pre-releases sort before the release they lead to: `0.1.0-alpha.1 < 0.1.0-beta.1 < 0.1.0-rc.1 < 0.1.0`.
Teams use alpha for "feature incomplete", beta for "feature complete, still finding bugs" and rc (release candidate) for "we intend to ship exactly this unless a test finds a problem".
These labels are optional, and a project already below 1.0.0 often needs none of them, because 0.y.z already says "not stable".

1.0.0 is a promise, not a milestone of effort.
It says "there is a public interface, it is written down, and from now on breaking it costs a MAJOR bump".
A project goes to 1.0.0 when someone outside the team depends on it and the team is ready to carry that promise.

A tag is a named pointer to one commit in git, so `v0.1.0` always means the same source.
A GitHub Release is a page attached to a tag, holding the notes and any downloadable files.

## Design

### Decisions already made

| # | Decision | Source |
| --- | --- | --- |
| 1 | The scheme is SemVer 2.0.0 | captain, via the brief |
| 2 | The first release is 0.1.0, with no earlier and no intermediate release before it | captain, via the brief. This replaces the 0.0.1 of issue #583, because 0.0.x signals "nothing settled", while the first release marks a proven base |
| 3 | 0.1.0 is cut once the proof of concept is done: the smoke gate, observability and the end-to-end acceptance suite | captain, via the brief; positions Gate, E15 and E16 in `docs/delivery/method.md:184-186`. Decision 12 refines the timing |
| 4 | The reference for shape is a private repository; this spec describes what it borrows in its own words and copies none of its text | captain, via the brief |
| 5 | Release notes live only in the GitHub Release body, and no `CHANGELOG.md` is committed | captain, 2026-11-20 (open question 1) |
| 6 | Release tags are SSH-signed, and the release recipe verifies the signature before publishing | captain, 2026-11-20 (open question 2) |
| 7 | A repository ruleset protects `refs/tags/v*` | captain, 2026-11-20 (open question 3) |
| 8 | A release publishes source only, with no container images | captain, 2026-11-20 (open question 4) |
| 9 | The notes generator is the captain's existing changelog generator from the reference repository, ported under `scripts/` and simplified for one product: no monorepo projects, no multi-file output, no ticket-tracker integration. Its category map, parsing approach and test approach stay | captain, 2026-11-20 |
| 10 | The generated notes are grouped under the type headers (Features, Fixes and the rest), never by epic. Each entry links its issue, epic or ticket, its PR and its commit, so a reader can reach the full context | captain, 2026-11-21 |
| 11 | The commit and merge message format is formalized in this spec, and the format binds every PR from the day this spec lands, so the history is clean when the first release is cut. The first release lists the whole history and does not require every older subject to conform | captain, 2026-11-21 |
| 12 | Release work waits until the main epics are in. The format and the generator land before then, and 0.1.0 is cut when the core features are in, before the hardening and load testing phase | captain, 2026-11-21 |
| 13 | A PR title that does not follow the commit format fails a required CI check, so a wrong title cannot merge | captain, 2026-11-21 (open question 6) |

### First version and pre-release labels

The issue weighs 0.0.1 against `0.1.0-alpha.1`, and the captain chose plain 0.1.0 (decision 2).
`0.1.0-alpha.1` is rejected because "alpha" would say "feature incomplete" about a build that is cut only after the proof of concept is complete.
0.0.1 is rejected because 0.0.x says "nothing settled", and 0.1.0 marks a base proven by the smoke gate, observability and the end-to-end suite.

This project uses no pre-release labels at all: no alpha, no beta and no release candidate.
Why: below 1.0.0 the version already says "not stable", and the only stages that matter here are "the gate passed" (a release) and "the gate has not passed" (no release).
A release candidate tag would add a name without adding a check, because the gate already runs on the exact commit before it is tagged.
What would change this: someone other than the captain having to test a fixed build before it is released, which the proof of concept plan does not have.
The spec is then updated in place with an `-rc.N` rule.

There is therefore no alpha-to-beta event.
The path is 0.1.0 when the proof of concept is done, further 0.y.z releases as the captain chooses, and 1.0.0 under the rule in "Compatibility below 1.0.0".

### What is versioned

The whole repository is one product with one version.
Recommendation: one version for the repository, and no per-package or per-image versions.
Why: nobody installs a single `dsy-*` package, pulls a single image, or deploys part of the system.
The packages are uv workspace members (`pyproject.toml:9`), images are built from source on every deploy (`deploy/dispatchapi/Tiltfile.module:21-26`) and pushed to the cluster's own local registry (`scripts/up.sh:2`), and the whole system comes up through one `just up`.
Independent versions pay off when separate consumers upgrade separate parts, and here there are none.

Two things keep their own counters, and the release does not touch them.
Each pinned contract has an integer `contracts/<name>/VERSION` (for example `contracts/events/VERSION` is 5), bumped by a contract-change PR as `docs/delivery/method.md:102` describes.
Third-party pins live in `deploy/versions.yaml`, `flake.lock` and `uv.lock`, as `docs/versions-policy.md` describes.
The release notes report contract versions that changed, so a reader sees interface breaks without reading every PR.

The 33 package manifests stay at `0.0.0`, which here means "internal, never released alone".
Bumping them in lockstep would touch 34 manifests and `uv.lock` every release for a number nothing reads.

### Where the version lives

The single source of truth is `version` in the root `pyproject.toml` (`pyproject.toml:3`).
The tag `vX.Y.Z` must equal it exactly, and the release recipe refuses to tag when it does not.
`uv.lock` repeats the root version (`uv.lock:678-679`), so a bump is the edit plus `uv lock`.
The tests run with `--frozen` (`scripts/test.sh:9-10`), which does not notice a stale lock, so the release recipe runs `uv lock --check` itself.
The file holds the last released version, except between a release PR's merge and its tag, when it holds the version being released.

Images, manifests and the Tilt modules carry no product version.
They are built from the checked-out source, so the tag already pins them.
If a later release publishes images, the image tag is the same `X.Y.Z`, set from the same file at build time.

### Tag format, who tags, and signing

Format: `vX.Y.Z`, always an annotated tag, always SSH-signed (decision 6).
Why `v`: it is what GitHub, Go tooling and most changelog tools expect, and it keeps tags apart from branch names.
Why no component prefix: the reference prefixes tags with a component path, because it releases many components independently, and this project releases one product.
Why annotated: an annotated tag records who tagged, when, and a message, where a lightweight tag is only a pointer.

Who: only the captain creates and pushes release tags, by running the release recipe.
Agents never push tags, as they never push to `main`.
A repository ruleset on `refs/tags/v*` blocks creation, update and deletion for everyone except the repository admin, so that rule is a setting and not only a habit (decision 7).

Signing: every release tag is signed with the captain's SSH key (decision 6).
A signed tag lets anyone check that the captain, and not someone holding push credentials, named that commit as the release.
SSH signing needs only an SSH key, where GPG would add a second key system with its own keyring to manage.
No signing setup exists today (`git config tag.gpgsign` and `gpg.format` are unset), so it is set up once before 0.1.0:

1. Register the public key on GitHub as a signing key, which is separate from registering it for authentication: `gh ssh-key add ~/.ssh/<key>.pub --type signing --title "release signing"`.
2. Tell git to sign with SSH and with that key: `git config --global gpg.format ssh` and `git config --global user.signingkey ~/.ssh/<key>.pub`.
3. Make every annotated tag signed: `git config --global tag.gpgSign true`, or pass `-s` to `git tag` each time.
   The recipe passes `-s` explicitly, so the release does not depend on step 3.
4. Add the public key to `.github/allowed_signers`, one line of the form `captain <key type> <key>`, so that `git verify-tag` works on any checkout.
   The file holds a public key only, which is safe to commit, and the principal is a name rather than an email address.

The recipe then verifies twice.
Before pushing, it runs `git -c gpg.ssh.allowedSignersFile=.github/allowed_signers verify-tag vX.Y.Z` and refuses on failure, so an unsigned or wrongly signed tag never leaves the machine.
After pushing and before creating the Release, it reads the tag object from the GitHub API and refuses unless its `verification.verified` is true, which proves GitHub links the signature to the captain's account and shows the tag as Verified.
A later key change is a new line in `.github/allowed_signers` and a new signing key on GitHub; old lines stay so old tags still verify.

### Release notes and changelog

Notes are generated from the commit subjects between the previous release tag (the highest `v*` tag) and the new one, then the captain adds a short hand-written summary on top.
This works because every PR is squash merged with a Conventional Commits title (`docs/delivery/method.md:59`), so each change is exactly one subject line such as `feat(acceptance): [#543] add the smoke driver with its boundary rows (#582)`.
304 of the 305 subjects on `main` start with a Conventional Commits type today, and the one that does not falls into "Other".

The generator is the captain's changelog generator from the reference repository, ported and then simplified (decision 9).
It becomes one stdlib Python module, `scripts/release_notes.py`, with its tests in `scripts/test_release_notes.py`, the same shape as `scripts/affected.py` and `scripts/test_affected.py`.
The original is a package of several modules and a command line built for many projects in one repository; one product needs a single module with three layers.

- Git layer: one `run_git` helper, the latest-tag lookup and the commit listing, ordered oldest first by commit time as in the original.
  The previous tag becomes the highest `v*` tag by version order, and with no tag it lists the whole history, where the original stopped and printed a message.
- Parser: a subject becomes a category, the ticket references and the message, as in the original.
  The category pattern is extended to accept `type(scope)!:`, because this repository's subjects carry a scope and the original pattern only matches a bare `type:`.
  Ticket references become GitHub issue references written `[#N]`, and the trailing `(#PR)` becomes a PR reference.
  A subject with no recognised type falls into Other, as in the original.
- Builder and formatter: entries are grouped by category and rendered in the order of the category map, with a count per section and a link per entry, as in the original.

The category map keeps the original's keys and order, Features, Fixes, Performance, Refactors, Documentation, Chores and Other, and adds Tests (`test`) and CI and build (`ci`, `build`) before Chores, because this repository uses those types and the original sends unknown types to Other.

What this repository adds on top of the port:

1. Breaking changes first: a `!` after the type puts the entry in a Breaking changes section above every category.
2. A Contract versions table after Breaking changes, listing every `contracts/*/VERSION` that differs between the two refs, old and new.
   For the first release it lists every contract at its current version, with the old column empty.
3. A placeholder for the hand-written summary at the top, and a Gate section skeleton at the end with the lines listed under "Release gate" below, for the captain to fill with evidence.
4. The target commit's full sha as the first line of the file, which the recipe checks at publish.

What the port drops, and why:

| Dropped | Why |
| --- | --- |
| Monorepo projects: per-project paths, ranges and leftover commits | one product, so every commit belongs to the one release |
| Multi-file output and the default `CHANGELOG.md` target | notes go only to the GitHub Release (decision 5), so the output is one notes file |
| Ticket-tracker integration and its URL mapping | issues are GitHub issues, linked from `[#N]` with no mapping |
| Collapsing by merge request and grouping by ticket | squash merges already give one commit per PR, and grouping many PRs under one epic issue would hide what each PR did |
| Several category blocks in one subject | a PR title has one type, and matching `word:` anywhere in a title would misfile text such as `note:` |
| Commit-message markers that skip or highlight an entry | the hand-written summary does the highlighting, and nothing needs hiding from a list of merged PRs |
| A category map passed on the command line | the map is fixed in the module |
| The heading with refs and dates, and merge request detection from the commit body | the GitHub Release supplies the title and date, and the PR number is in the subject |
| Links in the other forge's URL form | links use GitHub's `/commit/`, `/issues/` and `/pull/` forms, from the `origin` remote |

Notes live only in the GitHub Release body, and no `CHANGELOG.md` is committed (decision 5).
Why: the project keeps one source of truth per fact (`.claude/CLAUDE.md:31`), and a committed changelog would be a second copy of the release body that needs its own commit per release.
The GitHub Releases page already is the changelog, ordered and linked to tags.

The first release lists the whole history, about 300 entries.
That is acceptable for 0.1.0, because the hand-written summary on top is what a reader takes in, and the list is the audit trail.

### Commit and merge message format

Every PR is squash merged, and the PR title becomes the one commit subject on `main`.
The generator reads only that subject, so the title is the contract between a change and its release notes.
The format binds every PR from the day this spec lands.

`type(scope)!: [#issue] summary (#PR)`

- `type` is one of `feat`, `fix`, `perf`, `refactor`, `docs`, `test`, `ci`, `build`, `chore`.
  The type decides the header the entry lands under in the notes.
- `scope` is the area changed, such as a package or domain name, and is optional.
  It is shown in the entry and never changes the grouping.
- `!` after the type or scope marks a breaking change, which also lists the entry under Breaking changes.
- `[#issue]` links the GitHub issue the PR implements, which may be a lane issue or an epic issue.
  A PR with several issues lists each one, for example `[#12] [#13]`.
  A PR with no issue omits the part.
- `(#PR)` is added by GitHub on squash merge and links the PR.
- The summary is imperative, lower case and has no trailing full stop.

The notes group entries only under the type headers.
Epics, issues and PRs appear as links on each entry, so a reader reaches the exact issue or PR for more detail, and no entry is grouped under an epic.

Subjects before this spec landed may not conform.
They fall into Other, and the first release lists them as they are.

### Release gate

All of these must pass on the exact commit being tagged.

1. The `ci` workflow's `check` job concluded `success` on the push of that commit to `main` (`.github/workflows/ci.yml:3-6,85`).
   A `skipped` conclusion does not count, because the repository variable `CI_ENABLED=false` skips every job (`.github/workflows/kind-smoke.yml:12-17`).
2. The `kind-smoke` workflow concluded `success` on that push (`.github/workflows/kind-smoke.yml:3-5`).
3. `just smoke` passed once on a fresh cluster: `just nuke`, `just up`, a deploy on preset `ci` with `scripts/tilt/run.sh ci`, then `just smoke`, from a clean export of the commit.
   By 0.1.0 this includes the telemetry row the observability epic adds to `just smoke` (`docs/delivery/epics/17-acceptance-smoke.md:29`).
4. `just e2e` passed once on that same deploy (`just/acceptance.just:4-5`, a stub today at `scripts/e2e.sh`).
5. `just versions --check` passed, so every third-party pin has a digest (`docs/versions-policy.md`).

Checks 1 and 2 are read by the release recipe from the GitHub API, so they cannot be skipped by mistake.
Checks 3 to 5 run on the captain's machine, because CI does not run the smoke gate (`docs/delivery/epics/17-acceptance-smoke.md:31`), and their output is pasted into the Gate section of the release notes.
One run each is enough: the ten-pass rule (`docs/delivery/method.md:193`) proves the gate is stable, and the release run proves this commit passes it.
If CI later runs smoke or e2e, those rows move from pasted evidence to an API check.

### Release flow

The step-by-step version for the person cutting a release is the [release runbook](../runbooks/release.md).

Releases are cut from `main`, with no release branch.
Why: there is one line of development and no older release to maintain, and `main` stays green by rule (`docs/delivery/method.md:90-91`).

Steps for a release:

1. A release PR titled `chore(release): X.Y.Z` sets the root version and reruns `uv lock`, and nothing else.
2. The PR merges by squash, as every PR does.
3. The captain runs `just release X.Y.Z` with no other flag, which is a dry run.
   It checks that the working tree is clean, that `HEAD` equals `origin/main` (neither behind, ahead nor diverged), that `X.Y.Z` is a plain `MAJOR.MINOR.PATCH` equal to the root version, that `uv lock --check` passes, that no GitHub Release `vX.Y.Z` exists, and that gate checks 1 and 2 passed for `HEAD`.
   For a PATCH release (Z above 0) it also refuses when the range holds a `!` subject or a changed `contracts/*/VERSION`, because those may only ship in a MINOR release.
   It then writes the generated notes to `release-X.Y.Z.md` in the working directory, a path the recipe issue adds to `.gitignore`, and prints them.
4. The captain runs gate checks 3 to 5 on that commit and pastes their output into the notes file, then writes the summary.
5. The captain runs `just release X.Y.Z --publish`.
   It repeats the checks of step 3, and refuses when `HEAD` is not the sha on the first line of the notes file, so the evidence and the tagged commit cannot drift apart.
   It creates the signed tag with `git tag -s -a vX.Y.Z -m "vX.Y.Z" HEAD` and verifies it locally against `.github/allowed_signers`.
   It pushes the tag, checks that GitHub reports the tag as verified, and runs `gh release create vX.Y.Z --verify-tag --notes-file release-X.Y.Z.md` with the sha line stripped.

The publish step can resume.
If the tag `vX.Y.Z` already exists on `HEAD`, locally or on the remote, and no GitHub Release exists for it, the recipe skips creating the tag, runs both signature checks on the existing tag, pushes it if needed, and creates the Release.
A tag that exists on any other commit is a refusal.
A pushed tag without a Release is not yet published, but it is still never moved or deleted, for the reason given under "Withdrawing a bad release".

If any check fails after the release PR merged, the fix lands as ordinary PRs and the release is cut from the later commit.
The root version already says `X.Y.Z` in the meantime, which is harmless because nothing reads it and no tag exists yet.


### Withdrawing a bad release

A published tag is never moved or deleted.
Why: anyone who fetched it would then hold a different commit under the same name, which is the one thing a version must never mean.

To withdraw a release:

1. Fix forward: a PATCH release (`0.1.1`) for a fix, through the normal flow.
2. Edit the bad release with `gh release edit`: prefix its title with `[withdrawn]` and start its notes with one line saying what is wrong and which version replaces it.
3. Check that the new release is marked Latest on GitHub, which `gh release create` does by default for the highest version.

### What a release publishes

For 0.1.0: the GitHub Release page on the tag, with its notes, and the source archives GitHub attaches to every release automatically.
Nothing else.
Why: images are built from source by `just up` and its deploy, the packages are installed by `uv sync` from the workspace, and the docs are the repository at the tag.
Publishing images to GitHub Container Registry, or wheels to a package index, is not part of a release (decision 8), and is revisited only when something runs the system without a checkout.

### Compatibility below 1.0.0

- PATCH (0.1.0 to 0.1.1): fixes only.
  The API routes in `contracts/api/`, every pinned contract version, the `just` recipe names and the presets do not change.
  The recipe enforces the two parts it can see, `!` subjects and contract versions, and the captain judges the rest when reading the notes.
- MINOR (0.1.x to 0.2.0): anything may change, and every break is announced.
- A break is marked in the PR title with `!` after the type, for example `feat(api)!: drop the v0 status route (#NNN)`, and the PR body says what to change.
  The notes list these first under Breaking changes, and the Contract versions table shows any contract bump.
- 1.0.0 happens only when the captain decides that someone outside the project depends on the dispatch API and the job document, and the project will carry SemVer's MAJOR rule from then on.
  Nothing in the proof of concept plan needs that, so 1.0.0 is not on the roadmap.

After 0.1.0, later epics (checkpoint and resume, failure scenarios, the load CLI, characterization, `docs/delivery/method.md:187-190`) each ship as a MINOR release if the captain wants a named point for them, and none is required.

### What came from the reference, and what was left out

The private reference repository releases many Rust crates and Python packages from one repository, on another forge.

| Borrowed | How it is used here |
| --- | --- |
| Releases follow a version bump in a manifest, merged through review | the release PR of step 1 |
| A release is refused when its tag already exists | the recipe's existing-Release check |
| The changelog generator itself, with its category map, parsing approach and test approach | ported and simplified into `scripts/release_notes.py` (see "Release notes and changelog" for what it keeps and drops) |
| A release body template that says what the release is and how to get it | the generated notes skeleton, with a Gate section in place of download instructions |

| Left out | Why |
| --- | --- |
| A tag prefix per component, one release per package | this project ships one product (see "What is versioned") |
| CI that releases every package whose manifest version has no tag yet | one version needs no per-package detection, and the captain tags by hand |
| The generator's monorepo, multi-file, ticket-tracker and grouping features | listed with reasons in "Release notes and changelog" |
| Multi-architecture image publishing and package registry uploads | a release publishes source only (decision 8) |
| A reminder in every PR template to bump versions | only the release PR bumps the version |

### Tooling to build after approval

Filed as issues, in this order:

1. Release notes generator (#601): port the reference generator into `scripts/release_notes.py`, simplify it as "Release notes and changelog" describes, add the repository's sections, and port its tests to `scripts/test_release_notes.py`.
   The same issue adds the PR title check: a small script that reuses the generator's parser, and a workflow on pull request events that fails a title the parser rejects, so the format of "Commit and merge message format" is enforced from the day the generator lands.
2. Release recipe (#602): `just release X.Y.Z [--publish]` in a new `just/release.just`, wrapping `scripts/release.sh`, which runs the checks, calls the generator, creates and verifies the signed tag, and publishes.
   It also adds `release-*.md` to `.gitignore`.
3. Captain setup, no code: the one-time signing setup under "Tag format, who tags, and signing", including the `.github/allowed_signers` line, the tag ruleset of decision 7, and a ruleset on `main` that requires the PR title check to pass before merge (decision 13), all recorded in this spec when done.
   `main` has no branch protection today, so the title check blocks nothing until that ruleset exists.

Not filed: a release workflow in GitHub Actions.
Why: a workflow earns its place when a release builds and uploads artifacts, and a release publishes none (decision 8), so the recipe covers everything.
It becomes an issue only if decision 8 is revisited.
Not filed: a separate version-source issue, because the version already lives in `pyproject.toml` and the recipe's check is part of issue 2.
This knowingly narrows the four issues issue #583 lists (version source, release recipe, changelog tooling, release workflow) to two, and open question 5 asks the captain to confirm it.

## Validation

- `scripts/test_release_notes.py` follows the original generator's test approach: one group of tests per layer, with git replaced by patching `run_git`, so no test needs a repository, a network or a real tag.
  Parser tests feed fixed subjects: each type lands in its category, `type(scope)!:` is parsed, a subject with no type lands in Other, a subject with no `(#PR)` still lands in its category, and `[#N]` and `(#PR)` become links.
  Formatter tests feed built entries: sections follow the category map order with counts, Breaking changes and the Contract versions table come first, the Gate skeleton comes last, and the sha is the first line.
  Git-layer tests feed canned `git` output: the highest `v*` tag is chosen by version order, the whole history is used with no tag, a changed `contracts/*/VERSION` appears in the table, and with no previous tag every contract appears.
  One end-to-end test patches the git layer and checks the whole notes file, as the original's command-line test does.
- `scripts/release.sh` has a test that runs the recipe in a throwaway repository with a local bare remote and checks each refusal: dirty tree, `HEAD` behind, ahead of or diverged from `origin/main`, a version with a suffix or not equal to the root version, a stale lock, an existing Release, a failed or skipped CI conclusion, a PATCH range with a `!` subject or a contract bump, a tag on another commit, and a notes file whose sha is not `HEAD`.
  It checks the signature refusals: an unsigned tag, a tag signed by a key missing from the allowed signers file, and a GitHub verification result that is false.
  It also checks the resume path: a signed tag on `HEAD` with no Release is verified and goes straight to Release creation.
  The test signs with a throwaway SSH key and allowed signers file made in a temporary directory.
  The GitHub API and `gh release` calls are replaced by stubs in that test, so tags are pushed only to the local bare remote.
- Both tests run in `just ci`: the Python test sits beside `scripts/test_affected.py`, and the shell test is listed in `scripts/ci.sh` as `scripts/ci-paths.test.sh` is (`scripts/ci.sh:43`).

## E2E / Manual QA

The first real run is 0.1.0 itself, because a rehearsal elsewhere cannot pass gate checks 1 and 2 without this repository's CI.
The dry run is the rehearsal: it touches nothing remote, and its output is read before `--publish`.

| Case | Expected | Why |
| --- | --- | --- |
| Dry run on the merged release PR commit | pass, notes printed with Breaking changes, Contract versions (all contracts), the type groups and an empty Gate section | first release, so whole history and no old contract column |
| Dry run with one extra commit on `main` after it | `--publish` refuses on the sha line | evidence belongs to the earlier commit |
| `--publish` after gate checks 3 to 5 are pasted | pass, annotated tag `v0.1.0` on `HEAD`, a Release marked Latest | the normal path |
| `git cat-file -t v0.1.0` | `tag` | annotated, not lightweight |
| `git -c gpg.ssh.allowedSignersFile=.github/allowed_signers verify-tag v0.1.0` | `Good "git" signature for captain` | signed with the registered key |
| The tag on GitHub's tags page | marked Verified | GitHub links the key to the captain |

Observed results are appended here after 0.1.0 is cut.

## Open Questions

1. ~~Commit a `CHANGELOG.md`?~~ No: notes live only in the GitHub Release body (decision 5).
2. ~~Sign release tags?~~ Yes, SSH-signed, verified by the recipe before publishing (decision 6).
3. ~~Protect release tags with a repository ruleset?~~ Yes, on `refs/tags/v*` (decision 7).
4. ~~Publish container images with a release?~~ No, source only (decision 8).
5. File two implementation issues or the four issue #583 lists?
   Options: (a) two, the notes script and the release recipe, with the version check inside the recipe and no release workflow; (b) four, adding a version-source issue and a release workflow issue.
   Recommended: (a), because the version source needs no new code and a workflow has nothing to build while a release publishes source only (decision 8).
6. ~~Check that a PR title follows the format above?~~ Yes, a wrong title blocks the merge (decision 13).

## Out of Scope

- Cutting 0.1.0, which follows the end-to-end acceptance epic.
- A release workflow and image publishing to GitHub Container Registry, which follow only if decision 8 is revisited.
- Changing how contracts version themselves.

## Rollout / Migration

When approved, this file lands as `docs/delivery/release-process.md`.
It is a delivery process, not a system shape, so it sits beside `docs/delivery/method.md` and not under `docs/architecture/`.
The same PR adds one link line to the Delivery list in `.claude/CLAUDE.md` and one to `docs/delivery/method.md`, and corrects issue #583's "0.0.1" to 0.1.0 with a pointer to decision 2.
No existing file changes behaviour, and no tag exists to migrate.

## References

- Issue: https://github.com/AndoNorth/disyard/issues/583
- Semantic Versioning 2.0.0: https://semver.org/spec/v2.0.0.html (rule 4 for 0.y.z, rule 9 for pre-releases, rule 11 for ordering)
- Conventional Commits 1.0.0: https://www.conventionalcommits.org/en/v1.0.0/ (the `!` breaking marker)
- Delivery method: `docs/delivery/method.md` (squash merges at line 59, green `main` at 90-91, contract versions at 102, epic positions at 184-190, the gate at 193)
- Smoke gate spec: `docs/delivery/epics/17-acceptance-smoke.md` (decisions 11 and 13, lines 29 and 31)
- Version pins: `docs/versions-policy.md`
- Root version: `pyproject.toml:3`, and its lock entry `uv.lock:678-679`
- CI: `.github/workflows/ci.yml`, `.github/workflows/kind-smoke.yml`
- Image build: `deploy/dispatchapi/Tiltfile.module:21-26`, local registry `scripts/up.sh:2`
- Recipes: `just/acceptance.just`
- GitHub CLI release commands: `gh release create --verify-tag --notes-file`, `gh release edit`
