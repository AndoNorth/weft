# Dev setup

One Nix flake pins every tool, and `just` is the single entrypoint.
The same commands run on a laptop, on a second contributor's machine and in CI.
This document, `just doctor` and the CI `check` job are the verification surface of the dev environment.

## Host prerequisites

Only the following live outside the flake.
Everything else is pinned by `flake.lock`.

| Prerequisite | Needed because | Checked by `just doctor` |
| --- | --- | --- |
| Nix with `experimental-features = nix-command flakes` | provides the dev shell | `nix-flakes` |
| Docker engine, major version 24 or newer, daemon reachable | kind runs cluster nodes as containers | `docker-engine`, `docker-version` |
| WSL2 with systemd as PID 1 | the cluster tooling assumes systemd-managed Docker | `wsl-systemd` |
| cgroup v2 (unified hierarchy) | kind nodes require it | `cgroup-v2` |
| Repo on the WSL ext4 filesystem, not under `/mnt/c` | file watching and Nix evaluation over 9p are slow and unreliable | `repo-on-ext4` |
| `fs.inotify.max_user_instances` of at least 512 | many kind nodes and watchers exhaust the default | `inotify-instances` |

The Nix installation, flakes setting and Docker installation are the steps that stay unverified until a machine other than the author's host runs the doctor.

## Entering the shell

```sh
nix develop
```

This realises the flake tools plus `wasmtime` and `wasm-tools`, then sources `scripts/env.sh`.
A one-off command runs without an interactive shell:

```sh
nix develop -c just doctor
```

With direnv installed, `.envrc` (`use flake`, nothing else) enters the shell automatically.
It needs a one-time `direnv allow` in the repo root, and it is the recommended way to work in the repo day to day.
Both direnv and `nix develop` install the git hooks, see [Git hooks](#git-hooks).
`just` is only available inside `nix develop`, so outside the shell every recipe runs as `nix develop -c just <recipe>`.

A first realisation downloads roughly 886 MiB.
Later entries take seconds.

## Recipes

`just --list` prints every recipe name.
Recipes that are not built yet print `not implemented: owned by #N` and exit 3.
No logic lives in the justfile, and each real recipe calls `scripts/<name>.sh`.

| Recipe | Status | Owner | What it does |
| --- | --- | --- | --- |
| `doctor [--json]` | real | - | host preflight, see below |
| `versions [--check]` | real | - | prints tool versions and `deploy/versions.yaml`, `--check` validates the file against its schema |
| `lint` | real | - | ruff, yamllint, shellcheck, actionlint, kubeconform and nixfmt over the files each owns |
| `test` | real | - | `pytest -n auto --dist worksteal -m "not integration and not slow"`, one worker per core and idle workers steal queued tests, so `scripts/test.sh -n0` runs serial, nothing collected counts as success |
| `itest [domain]` | real | - | `pytest -m integration`, optionally limited to `packages/<domain>` |
| `contracts-map` | real | - | fails when a directory under `contracts/` has no row in the map of [contracts.md](contracts.md), or a row points at a missing path |
| `ci` | real | - | `lint`, `check-links`, `contracts-map` and its self-test, the `ci-paths` and `ci-shards` self-tests, `verify-lint`, then `test` and `itest` unless only documentation changed, then `nix flake check` |
| `pre-pr [base]` | real | - | the local gate before a pull request: the docs path of `ci`, the unit tests of the changed packages and their dependents, and the integration tests of the changed packages, see [CI](#ci) |
| `verify-lint` | real | - | checks each `verify-<domain>` skill has a `SKILL.md` named after its directory, passes when none exist |
| `pre-push` | real | - | the fast gate that the pre-push hook runs, see [Git hooks](#git-hooks) |
| `hooks-status` | real | - | prints whether the git hooks are installed for this checkout |
| `ports` | real | - | reports each host port a run binds that something already holds, with the holder's pid, start time and command, and exits 1, see [Port check](#port-check) |
| `up` | real | - | brings up the kind cluster `dsy` and its local registry for `DSY_PRESET` (default `ci`), after the port check when the cluster does not exist yet |
| `down` | real | - | stops the node containers and keeps the cluster, the registry and the host data directory |
| `nuke` | real | - | destroys the cluster, its registry and the host data directory of the preset that started it |
| `cluster-verify` | real | - | read-only checks that the cluster `dsy` matches `DSY_PRESET` (default `ci`): preset, pod slots, module budget, nodes, node limits, quotas, module readiness, live requests, pressure and loopback ports, one `ok` or `FAIL` line each |
| `smoke` | real | - | the smoke gate: attaches to the running `ci` cluster, checks every layer and runs one job to its known answer within 300 s, see [the validation matrix](runbooks/validation-matrix.md#the-smoke-rows) |
| `scan [deps \| images \| secrets]` | real | - | the security scans, see [Security scans](#security-scans) |
| `e2e` | real | - | the end-to-end run: the smoke gate, then the level 4 scenarios, in a 600 s budget, see [the test ladder](acceptance-ladder.md) |
| `load-test` | stub | load | load generation |
| `characterize` | stub | characterization | characterization run |

A stub fails the way a real failure does, so a script cannot mistake it for success:

```text
$ nix develop -c just load-test
scripts/load-test.sh
not implemented: owned by #14
error: recipe `load-test` failed on line 2 with exit code 3
```

### Port check

`nix develop -c just ports` lists every host port that something already listens on, and `just up` runs it before it creates a cluster.
The ports are the rows of `scripts/dev-ports.map` plus those of `deploy/host/ports.yaml`, and `DSY_SLOT` shifts the rows that carry a stride.
A port published by one of the `dsy-*` containers is labelled a leftover, and nothing is stopped or removed.
`lsof` and `ss` are host tools: without both the check exits 0 and prints an install hint.
The T1 helper of `dsy_itest` takes a free port when a port of its slot is held, so a squatter does not fail an integration test.

### T1 lock

`dsy_itest` keeps the host to two T1 containers with two lock files, `/tmp/dsy-t1.0.lock` and `/tmp/dsy-t1.1.lock`, shared by every worktree and agent on the host.
A session takes the files it declares (two when a collected test carries the marker `pair`) for its whole life, so `just itest`, `just ci`, `just ci --shard`, the integration step of `just pre-pr` and a direct `pytest -m integration` queue behind each other.
The tools that open a session of their own queue too: the corpus recorders of `packages/workflow` and `packages/temporal`, and the benchmarks of `packages/artifactclient` and `packages/stateops`.
A wait of 1800 s (`DSY_T1_LOCK_TIMEOUT` sets it) that runs out is a refusal, not a failure: the run prints `refused:` with the holders recorded in the lock files and exits 4, and no test is reported failed.
A full local `just ci` holds both files for longer than that wait, so a queued second run refuses and is started again when the first has finished.

### Observability switch

A local or smoke run that wants the observability stack brings the cluster up with `DSY_OBS=on nix develop -c just up` (after `just nuke` when the cluster exists with the switch off), and `scripts/tilt/run.sh ci` and `just cluster-verify` then follow the recorded value; the [Observability switch](cluster-host.md#observability-switch) section has the detail.

## Python with uv

`pyproject.toml` declares a uv workspace with `members = ["packages/*"]` and `requires-python = ">=3.13,<3.14"`.
Creating the environment from the lockfile:

```sh
nix develop -c uv sync --frozen
```

`scripts/env.sh` exports `UV_PYTHON_DOWNLOADS=never` and `UV_PYTHON_PREFERENCE=only-system` and unsets `UV_PYTHON`.
`UV_PYTHON_DOWNLOADS=never` alone does not keep uv on the flake's interpreter.
A uv-managed `cpython` already present in `~/.local/share/uv/python` still wins over the Python on PATH.
`only-system` makes uv choose the flake's Python, so `.venv/bin/python` is the interpreter in `/nix/store` and the same version on every machine.
`UV_PYTHON` stays unset because setting it breaks `uv pip`.

`scripts/env.sh` also adds a private directory with `libstdc++`, `libgcc_s` and `libz` from the host to `LD_LIBRARY_PATH`, so manylinux wheels such as numpy import under the Nix interpreter.
`DSY_LD_EXTRA=<dir>[:<dir>...]` appends further library directories.

Provenance check:

```sh
nix develop -c bash -c '.venv/bin/python --version; readlink -f .venv/bin/python'
```

The resolved path must start with `/nix/store/`.

## `just doctor`

```sh
nix develop -c just doctor
```

Each line is `ok|warn|fail <id>: <detail>`.
The exit code is 0 when no check fails and 1 otherwise, and a warning never fails the run.
`--json` prints `[{id,status,detail}]` instead.
Outside the flake shell the only result is `fail in-dev-shell`, because host copies of tools can shadow the pins.

| Check | Passes when | When it fails |
| --- | --- | --- |
| `in-dev-shell` | `IN_NIX_SHELL` is set | run through `nix develop -c just doctor` or enter the shell first |
| `nix-flakes` | `nix-command` and `flakes` are both enabled | add `experimental-features = nix-command flakes` to `~/.config/nix/nix.conf` or `/etc/nix/nix.conf` |
| `docker-engine` | `docker info` reaches a daemon | start the Docker service, and on WSL2 check that systemd is running and the user can reach the socket |
| `docker-version` | server major version is 24 or newer | upgrade Docker engine |
| `cgroup-v2` | `/sys/fs/cgroup/cgroup.controllers` exists | boot with the unified hierarchy, the WSL2 kernel does this by default and a `cgroup_no_v1=all` or v1 override in `.wslconfig` must be removed |
| `wsl-systemd` | PID 1 is systemd | set `[boot]` `systemd=true` in `/etc/wsl.conf`, then `wsl --shutdown` from Windows |
| `repo-on-ext4` | the repo is not under `/mnt/<drive>/` and not on a 9p, drvfs, cifs or nfs mount | move the clone under the WSL home directory, a `warn` means a non-ext4 local filesystem |
| `inotify-instances` | `fs.inotify.max_user_instances` is at least 512 | `sudo sysctl fs.inotify.max_user_instances=512`, persisted in `/etc/sysctl.d/` |
| `memory-vs-preset` | host memory covers `memory_mib` in `deploy/presets/$DSY_PRESET.yaml` (default preset `ci`), or `obs_memory_mib` with `DSY_OBS=on` | give WSL2 more memory in `.wslconfig`, and a `warn` with `DSY_OBS=on` means the host fits the preset only with the [observability switch](cluster-host.md#observability-switch) off |
| `path-provenance` | for every pinned tool (including `yq`, `wasmtime` and `wasm-tools`) the first match on PATH is a `/nix/store` path, not `~/.nix-profile` or `/nix/var/nix/profiles` | the detail prints `which -a` for each offender, so a profile copy ahead of the flake can be removed or PATH reordered |

`scripts/doctor.test.sh` is the fault-injection self-test.
It builds fixture trees and breaks one condition at a time (no docker, cgroup v1, repo under `/mnt/c`, low inotify, shadowing `helm`, flakes disabled, low memory, outside the shell).
Each fault must fail exactly the matching check, and the healthy tree must pass.

```sh
nix develop -c scripts/doctor.test.sh
```

## Security scans

```sh
nix develop -c just scan [deps | images | secrets]
```

`just scan` with no target runs all three, and `.github/workflows/scan.yml` runs each as a job on pushes to `main`, on pull requests and every Monday.
`deps` has Trivy scan every package locked in `uv.lock`, `images` builds every image of `deploy/*/image.sh` (one per worker pool) and has Trivy scan it, and `secrets` has gitleaks scan the whole git history.
A finding of high or critical severity fails the scan, and lower severities are not reported.
The images build on Docker, so `images` needs it running.
Trivy and gitleaks come from `flake.lock` like the other shell tools, and the Trivy database is fetched on every run.

`security/trivy-ignore.yaml` lists the accepted vulnerabilities.
Every entry carries a statement saying why it cannot be fixed now and an `expired_at` date, and a finding comes back as a failure once its entry expires.
`security/gitleaks.toml` extends the default rules with the paths that hold hashes or invented keys and no secret, each with its reason.
The gitleaks pre-commit hook reads the same file.

## Lint

```sh
nix develop -c just lint
```

The recipe runs ruff (check and format), yamllint (`--strict`, 120 columns), shellcheck, actionlint, kubeconform (over `deploy/**`, except the pins file) and nixfmt.
A linter with no files to check prints `skip <name>: no files`.
Lint works on a git checkout or on a `git archive` export, and it exits 1 when no file at all was linted in a tree that has files.
Config lives in `ruff.toml`, `.yamllint`, `.shellcheckrc` and `.editorconfig`, and not in `pyproject.toml`.
`scripts/fixtures/lint-bad/` holds one bad file per linter.
`scripts/lint.sh --self-test` proves each linter rejects its fixture, and `scripts/lint.sh --expect-fail <file>` does the same for one file.

## Git hooks

Entering the shell installs the git hooks, so `direnv allow`, `nix develop` and `nix develop -c <command>` are the only steps needed.
Every checkout and every linked worktree gets them on its first entry, because the shims live in the common git dir and each checkout links the rendered hook config as `.pre-commit-config.yaml` (git-ignored).
The hooks come from `git-hooks.nix` and run through `prek`.
The one config in `flake.nix` also builds `checks.pre-commit`, which `nix flake check` runs over the whole tree as part of `just ci`, so the local hooks and CI use the same tool list.

| Stage | Runs | On |
| --- | --- | --- |
| pre-commit | ruff format, ruff check, yamllint, shellcheck, actionlint, nixfmt | staged files |
| pre-commit | gitleaks, over the staged changes | staged files |
| pre-commit | trailing whitespace, end of file, merge conflict markers, large files | staged files |
| pre-push | `just pre-push <check>` for each of the lint steps, `verify-lint` and the lint self-test, each only when the pushed commits changed a file it concerns | the whole tree |

The formatters and whitespace fixers rewrite a file and fail the commit, so staging the rewritten file and committing again passes.
The lint fixtures, the byte-exact `contracts/**/vectors/` files and the generated draw.io diagrams are excluded.
A push that changes only docs runs none of the pre-push checks, and `just pre-push` without a name runs them all.
The pre-push gate is a subset of `just ci`, because the unit and integration tests and the flake check take minutes.
The CI jobs are the full gate.

Bypass either stage for one command with `--no-verify`:

```sh
git commit --no-verify
git push --no-verify
```

Check that the hooks are installed:

```sh
nix develop -c just hooks-status
```

It prints `ok config`, `ok pre-commit` and `ok pre-push` and exits 0, and prints `missing <part>` with the fix and exits 1 otherwise.
A `core.hooksPath` set in a git config file is never overwritten.
The shell then installs nothing and `hooks-status` reports it.
A checkout that never entered the shell has no linked config, so its shims do nothing and never block a commit.

## Pinned versions

Each pin, the file that holds it and how to bump it are in [versions-policy.md](versions-policy.md#where-each-pin-lives).

## CI

`.github/workflows/ci.yml` runs on pushes to `main` and on pull requests.
Its `changes` job picks the path and reads the test shards from `scripts/ci-shards.sh`.
Its `checks` job runs `nix develop -c just ci --checks`, which is the gate without the unit and integration tests, and on the full path a reproducibility check.
On the full path, one `test` job per shard runs at the same time on a runner of its own.
Each restores the build download cache and the uv cache, then runs `nix develop -c just ci --shard <name>`: the unit tests, then the integration tests, of that shard's paths, with the same markers as `just test` and `just itest`.
The `check` job passes when `checks` passed and every `test` job passed, or the docs path skipped them, so `check` is the one status to require.

Each line of the list in `scripts/ci-shards.sh` is a shard: a name, then the packages and top-level directories it runs.
The last shard names nothing and runs every path no other shard names, so a new package is tested before it is placed in a shard.
Adding a line adds a runner, and moving a package between lines rebalances the shards.
`scripts/ci-shards.test.sh` fails when a package, `deploy/` or `scripts/` would be run by no shard or by two, when a line names a missing path, and when the last shard names one.

The reproducibility check runs `git archive HEAD` into two fresh directories and evaluates `.#devShells.x86_64-linux.default.drvPath` in each.
The job fails when the two derivation paths differ, which stands in for a second contributor's machine.

A pull request whose changed files are all documentation takes the docs path, and every other change and every push to `main` takes the full path.
`scripts/ci-paths.sh` decides, and `scripts/ci-paths.test.sh` lists which paths count as documentation.
The docs path runs lint, the link check, the contracts map, the self-tests, the verify-skills lint and `nix flake check`, whose `checks.pre-commit` reads documentation too.
It skips the `test` jobs, the reproducibility check and the `kind-smoke` cluster run.
Each skipped job still reports as skipped, so a check made required later never stays pending.

The image builds, `deploy/workers/image.sh` and `deploy/workflow/image.sh`, read the wheels that `uv.lock` pins and the release assets of `nix/wasm-tools.nix` from the build download cache before the network, locally as in CI.
A second build on the same host downloads nothing, and every cached file is checked against its pinned hash before use.
The cache is `~/.cache/disyard/build` (under `XDG_CACHE_HOME` when set, or `DSY_BUILD_CACHE`), removing it is always safe, and `actions/cache` carries it between runs of the `test` jobs and `state-modules`.
`actions/cache` also carries `~/.cache/uv`, keyed by `uv.lock` alone, so a `test` job neither downloads the wheels nor builds `python-qpid-proton` from its sdist again.

CI can be switched off in two ways:

- Setting the repository variable `CI_ENABLED` to `false` skips every job through the job-level `if` of `changes` and `check`.
  Any other value, or no variable, leaves it on.
- A commit message containing `[skip ci]` skips the runs natively in GitHub Actions.

Locally, `nix develop -c just pre-pr` is the gate before a pull request, and the pull request's CI run is the full proof.
It runs the docs path of `just ci`, then, in parallel as `just test`, the unit tests of every package changed against the merge base with `origin/main` and of every workspace member that depends on one of them, then the integration tests of the changed packages.
`scripts/affected.py` reads the dependencies from the `[tool.uv.sources]` table of each `packages/*/pyproject.toml`.
A change outside `packages/` that `scripts/ci-paths.sh` does not count as documentation, such as `scripts/`, `deploy/`, `contracts/`, `uv.lock`, `pyproject.toml` or the flake, can reach tests that no package owns.
`just pre-pr` then prints `full run required` with the path and exits 1 without running anything, and the full run is needed instead.
A stacked branch passes its base, as in `just pre-pr <base branch>`.

`nix develop -c just ci` is the same gate as the CI jobs together, with every shard's tests in one run.
On a full path that is the CI shards one after another on one host, about an hour of serial work against about 12 minutes of CI wall time, so it is not the local default.
When `just pre-pr` prints `full run required`, run `nix develop -c just ci --checks` (about 30 seconds, lint, links, self-tests and the flake check) and then `just ci --shard <name>` for the shard that owns the tests the change can reach.
The pull request's CI run covers the rest.
It takes the docs path when every file changed against the merge base with `origin/main`, uncommitted and untracked files included, is documentation.
`just ci --docs` and `just ci --full` force a path, and `just ci --shard <name>` runs one shard's tests as CI does.
Lint on the workflow file is part of it, so a line over 120 columns in `ci.yml` fails before the push.

Integration tests hold a host-wide lock, shared by every worktree and agent on the machine.
`just itest`, `just ci --shard`, a full `just ci`, `just pre-pr` (its integration step) and a direct `pytest -m integration` queue on `/tmp/dsy-t1.*.lock`, while `just test`, `just ci --checks` and `just ci --docs` do not.
Any run that includes a package with `pair` tests takes both lock files, so it excludes every other integration run on the host until its pytest process exits.
A waiter polls for 30 minutes and then fails with `LockTimeout`, which reads like a test failure; `DSY_T1_LOCK_TIMEOUT` overrides the wait.
A full `just ci` holds the lock for most of an hour, so another agent's integration run started meanwhile times out.
Run one integration command at a time per host, and prefer one `--shard` over the whole run.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `fail in-dev-shell` | the command ran outside the shell, use `nix develop -c just doctor` |
| `fail path-provenance` naming `kind`, `kubectl`, `helm` or `yq` | a copy in `~/.nix-profile` is ahead of the flake, remove it with `nix profile remove` or run inside `nix develop` |
| `fail docker-engine` | daemon is down or unreachable, start Docker and confirm `docker info` works outside the shell |
| `fail cgroup-v2` or `fail wsl-systemd` | WSL2 configuration, see the table above, then `wsl --shutdown` |
| `fail repo-on-ext4` | the clone is on a Windows drive, clone again under the WSL home directory |
| `fail inotify-instances` | raise the sysctl as above |
| `warn memory-vs-preset` with `DSY_OBS=on` | the host fits the preset only with the observability switch off, give WSL2 more memory or leave the switch off |
| `uv sync` picks a different Python | `UV_PYTHON_PREFERENCE` is not `only-system`, which means the shell was not entered through the flake |
| `error: experimental feature 'flakes' is disabled` | Nix config lacks flakes, see `nix-flakes` |

## What green looks like

On a clean checkout, with the host prerequisites in place:

- [ ] `nix develop -c just doctor` exits 0, prints no `fail` line, and prints an `ok path-provenance` line saying the tools resolve first to the flake.
  A `warn memory-vs-preset` is acceptable only with `DSY_OBS=on`, see the table above.
- [ ] `nix develop -c just --list` prints the recipe table above, one name per recipe.
- [ ] `nix develop -c just ci --checks` exits 0, ending with `all checks passed!` from `nix flake check`.
  The unit and integration tests run in CI, one `just ci --shard <name>` per shard.
- [ ] The reproducibility check prints one `/nix/store/...-nix-shell.drv` path and exits 0.
  The two exports give the same path, otherwise it prints `drvPath differs` and exits 1.
- [ ] The CI `check` job is green on the pull request.

With a cluster, which needs the [operator runbook](runbooks/operator.md):

- [ ] `nix develop -c just up` ends with `cluster dsy ready: preset ci, DSY_OBS=off, 6 nodes`, and `scripts/tilt/run.sh ci` exits 0.
- [ ] `nix develop -c just cluster-verify` exits 0 with no `FAIL` line.
- [ ] `nix develop -c just smoke` exits 0 and ends with `smoke ci: 11 ok, 0 failed, 0 skipped, <s> s`.
- [ ] `nix develop -c just nuke` ends with `cluster dsy, registry dsy-registry and <data dir> are gone`, and the checks of [confirming nothing is left](runbooks/operator.md#confirm-nothing-is-left-behind) pass.

## Runbooks

[docs/runbooks](runbooks/README.md) links the operator runbook, the validation matrix, triage by symptom and the response to every alert rule.
