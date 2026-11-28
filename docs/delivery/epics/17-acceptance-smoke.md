# Epic #17 pass 1: Smoke gate - breakdown

Status: closed 2026-11-26
Epic: https://github.com/AndoNorth/disyard/issues/17
Architecture note: none new, and `docs/architecture/01-system-context.drawio` is unchanged, because the gate adds a host-side test entry point and package but no deployed component, data path or contract; the ladder document of pass 2 is where the test levels are described
Depends on (closed epics): #1, #2, #4, #5, #3, #12, #11, #6, #9, #10, #7, #8, #24

Citations were checked on `main` at `a1e90ac` on 2026-11-19, and all paths are relative to the repository root.
Tiers as in the sibling specs: T0 host Python with no runtime, T2 the cluster from `just up` plus `scripts/tilt/run.sh ci` on preset `ci`.
Every command takes `nix develop -c`, and every T2 command runs under `/tmp/dsy-cluster.lock`.
Figures marked "estimate" are proposals replaced by the first measured run.

## 0. Decisions

### 0.1 Settled decisions

| # | Decision | Source |
| --- | --- | --- |
| 1 | Smoke is a gate, not a behaviour test, uses a level 0 workload, budget under 5 min, enforced by a timer in the recipe | epic #17 ladder row 3 and key decisions |
| 2 | The gate builds on `dsy_clusterkit` and adds no parallel helper set | captain, via the brief; https://github.com/AndoNorth/disyard/pull/524 (merged) states the purpose "so the smoke gate can build on one kit instead of writing a fourth copy" |
| 3 | `scripts/smoke.sh` and `just smoke` are this epic's stubs; the stub prints `not implemented: owned by #17` and exits 3 | `scripts/smoke.sh:1-5`, `just/acceptance.just:1-2`, `01-dev-environment.md:68,113` |
| 4 | `just cluster-verify` is #2's infrastructure half of smoke and is meant to be called by it | epic #17 ladder row 3, `scripts/cluster-verify.sh:2-3` |
| 5 | The dispatch API is the public surface; the dispatch smoke driver and the admission drive are prior art to consolidate | captain, via the brief |
| 6 | The gate and its ten-pass exit are as `method.md:187` defines them | `method.md:187` |
| 7 | The single-owner cluster rule: take `flock /tmp/dsy-cluster.lock`, refuse a cluster you did not start | `method.md:93`, `02-cluster.md:146-147` |
| 8 | Broker: the smoke publishes through #24, consumes through #8 only, and uses `dlq list` to show the run left no dead letter | `10-broker.md:260,370` |
| 9 | Workloads: #17 uses the level 0 vectors and `dsy_kernel.check` | `07-workload-toolchain.md:114`, `contracts/workload/README.md:142` |
| 10 | Q1: the gate makes the deployed workflow worker build current after a fresh deploy, through one shared helper that replaces the two copies of `_first_current` (`packages/workflow/src/dsy_workflow/harness/cluster.py:116-134`, `packages/dispatchapi/src/dsy_dispatchapi/smoke/__init__.py:595-613`) and that the harness, the dispatch smoke driver and the gate all call. Why: the gate still passes after a fresh deploy without a change to #6's deploy, and the move deletes a copy instead of adding a third | captain, 2026-11-19 (option b) |
| 11 | Q2: no telemetry step in pass 1; the observability epic #13 adds its own row to `just smoke` as part of its exit. Why: observability is not deployed on `ci` (`deploy/dummy/obs/module.yaml:3,18`), and scraping raw metrics endpoints is not the epic's assertion | captain, 2026-11-19 (option a) |
| 12 | Q3: "ten consecutive passes" (`method.md:187`) means ten `just smoke` runs back to back on one deploy, plus two fresh `just nuke`, `just up`, deploy and `just smoke` cycles. Why: back-to-back runs alone never see a cold first compile, the budget's swing factor, and ten fresh cycles cost over an hour for little more signal | captain, 2026-11-19 (option c) |
| 13 | Q4: CI does not run the gate in pass 1; the exit test records one measured local run and pass 2 decides on a CI job. Why: no runner has ever deployed the services, and `ci` was sized for a runner on paper only (`deploy/presets/ci.yaml:1`) | captain, 2026-11-19 (option a) |
| 14 | Q5: the gate's code lives in a new package `packages/acceptance` (`dsy_acceptance`) on `dsy_clusterkit`, holding small clients (API, Temporal, store, broker) and the gate as an ordered driver `python -m dsy_acceptance.smoke`; pass 2's e2e is pytest over the same clients. Why: the gate is ordered steps where a later step needs an earlier one, so a driver with `ok`/`FAIL` lines matches `cluster-verify` and the existing drivers, and the clients are written once for both passes | captain, 2026-11-19 (option a) |
| 15 | The broker row records the dead-letter count before the job and fails only if it rises after it ("no rise"), not when it is non-zero | captain, 2026-11-19, spec review |
| 16 | The ladder document is not written in this pass; it stays with pass 2 | captain, 2026-11-19, spec review |
| 17 | `cluster-verify` runs inside the 300 s budget | captain, 2026-11-19, spec review |
| 18 | The wrapper deliberately differs from `scripts/up.sh:19-21` on a lock-wait timeout: it exits 4 (refused), where `up.sh` and `cluster-verify.sh` exit 1 | captain, 2026-11-19, spec review |
| 19 | The shared helper of decision 10 returns what it saw: the current build, the deployed builds and the build it made current, or none. R.1's acceptance asserts that result, and row 4 prints the deployed builds from it, so the gate needs no second listing of them | captain, 2026-11-19, post-fix review (option a) |
| 20 | 0.1 declares the acceptance package's full dependency set up front: `temporalio`, `dsy-workflow`, `dsy-broker`, `dsy-kernel`, `dsy-workloads` and `dsy-clusterkit`, a departure from `method.md:84` that section 3 states | captain, 2026-11-19, post-fix review (option a) |

### 0.2 Questions for the captain

None open: Q1 to Q5 are settled as decisions 10 to 14, the spec review's choices as decisions 15 to 18, and the post-fix review's as decisions 19 and 20.

### 0.3 Defaults the lanes build on

| # | Default | Why |
| --- | --- | --- |
| D1 | Preset `ci` only. `dev` and `full` deploy no pool workers (`deploy/workers/compile/module.yaml:25`, `11-workers.md:77`), so `just smoke` on another preset exits 2 with that reason | a gate that cannot pass on a preset should say so, not fail |
| D2 | The job is #24's runnable template: compile `build` of the workload library bundle (entry `dsy_workloads.main`), simulate `sim` with `echo_params()`, aggregate `agg` with `digest_list` (`packages/dispatchapi/src/dsy_dispatchapi/smoke/__init__.py:155-182`). The contract vector `contracts/job/vectors/valid/level0-echo.json` is not runnable (placeholder source, entry `echo`, non-golden args) | the aggregate pool is a layer the gate should see; the template is already measured at 66 s |
| D3 | Assertions read public surfaces: the control API status (it carries `results[]` with `uri` and `sha256`, `packages/dispatchapi/src/dsy_dispatchapi/reads.py:41,69,98`) and the result object fetched with the read-only `export` store identity (`contracts/store/roles.yaml:30-31`). Boundary probes are the only non-API reads, all read-only, and the one write outside the API is the shared helper of decision 10 | epic key decision "public surfaces only, any direct read explicit" |
| D4 | The boundary rows always all run, each under its own deadline, except that a refusal from `cluster-verify` ends the run at once with exit 4. The job rows run only when every boundary row is ok | the failure points at a layer, and a dead layer does not burn the job timeout |
| D5 | The aggregate's `summary.json` is asserted present with a matching `sha256`, not by value; value checks of the aggregate stay with e2e step 6 | lowest level wins; the gate needs a known answer, which the simulate result gives |
| D6 | Deadlines, estimates: `cluster-verify` (row 1) 90 s, every other boundary probe 15 s (`PROBE_S`), the shared helper's poller wait 30 s; the job rows share what is left of the 300 s budget less 30 s kept for rows 8 to 10 and the cleanup | each row ends on its own deadline, so a dead layer fails its own row and the rest still print |

## 1. Goal and non-goals

Goal: after a deploy, one command says whether the platform is healthy, in under 5 minutes, by checking that every layer answers and that one level 0 echo job goes through intake, admission, placement, the compile, simulate and aggregate pools and storage and produces the known answer.
A pass is the precondition for e2e, load and characterization.

The epic's smoke flow has five steps; this pass delivers steps 1 to 4, and step 5 ("Telemetry is flowing") moved to #13, which adds its own row to `just smoke` as part of its exit (decision 11).

Non-goals, deferred:

- To pass 2 of #17: the e2e acceptance suite in pytest over `dsy_acceptance`'s clients, with Postgres, Temporal history, CloudEvent and trace assertions; the two-chain acceptance job and its fixtures; the aggregate value check; the cache-hit check; all negative and control checks; the flake loop recipe and its reporting (the ten-pass exit of this gate is an exit test row, decision 12, not a recipe); the ladder document (decision 16); whether CI runs the gate, decided from the measured local run of exit row 3 (decision 13); and the epic's open question on direct Postgres reads (this pass reads none).
- To #13: telemetry rows (decision 11).
- Any cluster start, deploy or teardown: the gate attaches to a running cluster and never starts one.

### 1.1 What exists and what the gate does with it

| Prior art | What it is | Gate takes | Gate leaves |
| --- | --- | --- | --- |
| `just cluster-verify` (`scripts/cluster-verify.sh`) | read-only infra checks, ten rows, own lock unless `DSY_CLUSTER_LOCK_HELD` | called by the driver as row 1, under the wrapper's lock; its exit 4 and exit 2 end the run with the same exit | unchanged |
| Dispatch smoke driver, `run` scenario (`smoke/__init__.py:155-189,230-283,392-399,544-550`) | uploads the bundle, submits the echo template via NDJSON, polls status every 0.5 s up to `JOB_S = 1800`, cancels a batch | the job shape (`template`, `batch`) and the upload, submit, status and batch-cancel calls, written into `dsy_acceptance.clients.api` (C.1); R.2 makes the driver import them back so there is one copy | its other scenarios (#24's exit rows 10-15) stay in `dsy_dispatchapi.smoke`; closed epic text is not rewritten |
| Harness `matches_echo`, `echo_params`, `ECHO` (`harness/__init__.py:86-88,244,261-271`) | host-side echo check | the gate calls `dsy_kernel.check` on the fetched `results.xml` (the epic's named check); `matches_echo` stays the harness's | unchanged |
| `_first_current` (two copies, `harness/cluster.py:116-134`, `smoke/__init__.py:552-558,595-613`) | makes the deployed build current | the shared helper of decision 10, which R.1 moves the harness copy into and R.2 moves the driver onto | both drivers call the shared helper |
| Admission drive (`dsy_admission.drive`) | admission journeys on host fake pools | nothing: it fakes the dispatch accept and mutates the admission Deployment env (`drive/__init__.py:4-8,108-125`), which a gate must not do | stays #8's tool |
| `dsy_clusterkit` | forwards, kubectl, readiness, polling, credentials | every cluster call of the gate goes through it; 0.1 adds the `timeout_s` parameter of `Forward.open`, because its fixed `UP_S = 300` wait (`__init__.py:26,86-98`) equals the whole budget | no lock or summary added to it: the shell wrapper owns the lock as `up.sh`/`down.sh` do, and the summary format is the gate's own |
| CI `kind-smoke` (`.github/workflows/kind-smoke.yml`) | `just up`, `just down` on every non-docs PR, 30 min timeout | nothing in pass 1 (decision 13) | unchanged |

### 1.2 Boundary rows, one per layer

Each row covers only what `cluster-verify` does not.
Its `ready` check already runs each `ci` module's readiness rule (`scripts/cluster-verify.sh:154-167`): admission is `deployment/admission Available` (`deploy/admission/module.yaml:22-24`), each pool is `kubectl wait --for=condition=Available deployment/<pool>-worker` (`deploy/workers/compile/module.yaml:16-24`), the object store is `statefulset/objectstore Ready` with the `store` container ready on `GET /healthz` (`deploy/objectstore/module.yaml:15-17`, `deploy/objectstore/README.md:14`), and the four buckets are `scripts/storage/store/bootstrap.sh check` (`deploy/objectstore/bootstrap/module.yaml:15-16`).
So admission, the three pools and the object store have no row of their own, and a failure there is named on row 1 through `cluster-verify`'s `FAIL ready not ready: <names>` line.

All probes are read-only and go through `dsy_clusterkit.Forward` on 127.0.0.1, opened with `timeout_s=PROBE_S`, unless the port is published.
Row 4 is the one exception to read-only: on the first run after a fresh deploy it makes the deployed build current (decision 10).

| Row | Layer | Probe | Pass line |
| --- | --- | --- | --- |
| 1 | Cluster, modules, admission, pools, object store | `scripts/cluster-verify.sh` as a subprocess under the held lock, ended at 90 s (D6) | exit 0; its count line copied. Exit 4 or 2 ends the run with that exit and no other row. Exit 1 prints `FAIL cluster-verify` with its `FAIL` lines; the deadline prints `FAIL cluster-verify did not finish in 90 s` with the last check line it printed |
| 2 | Dispatch API | `GET /readyz` on `127.0.0.1:18081` and `:18080` (readiness covers the logins, a store head and Temporal, `deploy/dispatchapi/README.md:88,94-95`) | both `200 {"status":"ready"}` |
| 3 | Intake broker | `python -m dsy_broker.dlq list` as `operator` over a forward of `svc/rabbitmq:5672`; RabbitMQ has no management API (`packages/broker/src/dsy_broker/topology.py:173`) | exit 0; the dead-letter count is recorded as the baseline of row 10, and a non-zero count passes (decision 15) |
| 4 | Temporal | client connect over a forward of `svc/temporal-frontend:7233`, describe namespace `dsy`, then the shared helper of decision 10 with its poller wait at 30 s | namespace answers and a deployed build is current; the row names the current build and the deployed builds from the helper's result (decision 19), and says when it made the build current |
| 5 | Placement | `GET /pools` over a forward of `svc/placement:8080` (`packages/placement/src/dsy_placement/service.py:210-213`) | 200 and the three pools of `contracts/temporal/naming.yaml:16-19` listed |
| - | Postgres | none: row 2's `/readyz` connects every login, and job row 7 reads status from the row; no direct SQL (D3) | no row |
| - | Observability | none in pass 1 (decision 11) | no row |

### 1.3 The level 0 job rows

Workload: `echo` (`packages/workloads/src/dsy_workloads/level0.py`), the fixture both existing drivers already use.
Known output: the `expected.json` of `contracts/workload/vectors/level0/echo/`, one `echo` block `args` with one row per key of the `args` of that vector's `input.json`, at its seed.
The literal seed stays in the template because only placeholders bind to the batch entry's seed (`packages/plan/src/dsy_plan/binding.py:126-138`).

| Row | Step | Assertion |
| --- | --- | --- |
| 6 | Upload and submit | build the bundle on the host (`python -m dsy_workloads.bundle`), `PUT` it (201 or 200), submit one job under batch key `smoke-<12 hex>` for tenant `acme` (first `ci` tenant, `contracts/tenancy/tenancy.yaml:16-18`) | answer `accepted` with a job id |
| 7 | It runs and ends | poll control status every 0.5 s through `dsy_clusterkit.until`, bounded by the remaining budget less 30 s (D6); `detail` is filled only while the status is `admitted`, `running`, `paused` or `resume-pending` and is `null` once the job ends (`packages/dispatchapi/src/dsy_dispatchapi/reads.py:40,72-78`), so `detail.tasks` is read from the samples taken while the status is `running` | status passes `running` and ends `succeeded`; a `running` sample shows task `build` in state `succeeded`, and the row says it ran (`task_attempt` 1 or more) or hit the cache (`task_attempt` 0, `packages/workflow/src/dsy_workflow/models.py:323-326`) |
| 8 | Result | fetch the `sim` result reference from `results[]` with the `export` identity, check its `sha256`, run `python -m dsy_kernel.check results --input contracts/workload/vectors/level0/echo/input.json --results <file>` | sha matches, check exits 0 |
| 9 | Aggregate | the `agg` `summary` reference exists and its object's `sha256` matches (D5) | present and matching |
| 10 | No dead letters | row 3's probe again | count not above row 3's baseline (decision 15) |

A job row runs only when the rows before it are ok, and prints `skip` otherwise; row 10 runs whenever row 3 was ok and row 6 submitted a job.
When a job row fails, or the budget runs out, after row 6 submitted, the driver cancels the batch through `POST .../batches/<key>/cancel` before it prints the count line, so a late job does not hold the single-replica pools into the next back-to-back run.
Unique batch key per run means repeated gates on one cluster never dedup against each other, and the compile may hit the cache on runs after the first, which the epic allows ("a compile ran or hit the cache").

### 1.4 Entrypoint, lock, budget

`scripts/smoke.sh`:

1. Usage: `DSY_PRESET` must be `ci` (D1), and `kind`, `kubectl`, `flock`, `timeout` and `uv` must be on `PATH`, else exit 2.
2. Take `flock -w 900 /tmp/dsy-cluster.lock` unless `DSY_CLUSTER_LOCK_HELD` is set, as `scripts/up.sh:19-21` and `scripts/cluster-verify.sh:26-29` do, but on a wait timeout print `refused: could not take /tmp/dsy-cluster.lock in 900 s` and exit 4 (decision 18); export `DSY_CLUSTER_LOCK_HELD=1` for children.
3. Run `timeout -s INT -k 10 300 uv run --frozen python -m dsy_acceptance.smoke`, as `scripts/test.sh:8` runs pytest (the budget excludes the lock wait and includes `cluster-verify`, decision 17).
   The driver runs every row, row 1 included, prints each row with a flush, prints the count line with the elapsed seconds, and exits 0, 1, 2 or 4 as in section 2.
4. On the timer, `timeout` sends SIGINT: the driver prints `FAIL budget 300 s ran out in <row>`, cancels its batch if it submitted one (section 1.3), prints the count line and exits; `timeout` then exits 124, which the wrapper maps to exit 1.
   If the driver is still running 10 s later, `timeout` kills it and exits 137, and the wrapper prints `FAIL budget` and `smoke ci: budget ran out after 300 s` itself and exits 1.

Attaching to a running cluster is `cluster-verify`'s ownership check (no cluster `dsy`, or `cluster.owner` not equal to the preset, gives exit 4); the gate never starts, deploys or tears down.
A cluster stopped by `just down` is still listed by `kind get clusters`, so it is not refused: `cluster-verify` fails on its first live check and row 1 fails (`scripts/down.sh:2`, `docs/cluster-host.md:96-99`).
The gate relates to a deploy as "`just up`, `scripts/tilt/run.sh ci`, then `just smoke`"; `run.sh` takes no lock today (`scripts/tilt/run.sh:1-13`), which is #2's gap, not this gate's, and is listed under risks.

Budget, estimate: `cluster-verify` 20 to 40 s (never measured), the other boundary rows about 10 s including forwards, bundle build a few seconds, the job 66 s measured once (`13-dispatch-api.md:806`), so about 2 min with headroom under the 5 min timer.

## 2. Interfaces

### Consumes (each pinned to a version)

Every dependency is merged, so no stub stands in for one.
The two `revisit` child issues this pass files against closed epics are listed last.

| From | What | Pinned at | Stub used until it exists |
| --- | --- | --- | --- |
| #2 | `just cluster-verify`: `ok`/`FAIL` lines, count line, exit 0/1/2/4, honours `DSY_CLUSTER_LOCK_HELD` (`:11`, `:26-33`, `:218-229`) | `scripts/cluster-verify.sh` on `main` | none, merged |
| #24 | `POST /v1/tenants/{t}/batches` (NDJSON), `PUT .../objects/source/{sha256}`, `GET .../jobs/{id}` and `POST .../batches/{batch_key}/cancel` on control, `/readyz` on both listeners (`:6-19`, `:46-51`, `:61-67`, `:76-81`) | `contracts/api/routes.yaml` | none, merged |
| #24 | Host ports `127.0.0.1:18081` dispatch, `127.0.0.1:18080` control (`:4-10`) | `deploy/host/ports.yaml` | none, merged |
| #11 | Level 0 `echo` vector, `dsy_kernel.check`, the workload library bundle | `contracts/workload/vectors/level0/echo/`, `packages/kernel/src/dsy_kernel/check.py:1-8,34-60`, `packages/workloads/src/dsy_workloads/bundle.py` | none, merged |
| #12, #4 | Result layout `dsy-results/<tenant>/<batch>/<job>/<seed>/<task>/<attempt>/results.xml`, four buckets | `contracts/artifact/layout.yaml:4-8,15-18` | none, merged |
| #7 | `python -m dsy_broker.dlq list`, exit 0/1/2/3 | `packages/broker/src/dsy_broker/dlq.py:1-17` | none, merged |
| #6 | Namespace `dsy`, pool queues, `versioning.current`, `versioning.set_current` | `contracts/temporal/naming.yaml:3-19`, `packages/workflow/src/dsy_workflow/versioning.py:99,115` | none, merged |
| `dsy_clusterkit` | `Forward`, `kubectl`, `reachable`, `ready`, `until`, `state_dir`, `appdb_password`, `store_credentials`, `Refused`, `INFRA`/`CONTROL`/`WORKERS`/`UP_S` (`:22-171`) | `packages/clusterkit/src/dsy_clusterkit/__init__.py` on `main` | none, merged |
| #6, `revisit` | R.1: the shared helper of decision 10 in `dsy_workflow` | child issue of #6, filed from R.1 | none: R.1 merges before G.1 |
| #24, `revisit` | R.2: the dispatch smoke driver calls the shared helper and imports the API client back | child issue of #24, filed from R.2 | none: R.2 merges before G.2 |

### Produces (each pinned precisely)

| To | What | Where it lives (path) | Shape | Version |
| --- | --- | --- | --- | --- |
| #13, #14, #16, #18, pass 2 | `just smoke` | `just/acceptance.just` (recipe unchanged), `scripts/smoke.sh` | exit codes and summary below; preset from `DSY_PRESET` (default `ci`) | smoke recipe v1, replacing the stub's exit 3 |
| pass 2 | small clients over the API, store, Temporal and broker | `packages/acceptance/src/dsy_acceptance/clients/api.py`, `store.py`, `temporal.py`, `broker.py` | `api`: `template`, `batch`, `Api(dispatch, control, tenant)` with `upload_source`, `submit_one`, `status`, `cancel_batch`; `store`: `fetch(uri, identity) -> bytes`; `temporal`: `connect(address) -> Client`; `broker`: `dead_letters(address) -> int`; documented in the package README | v0, extended by pass 2 |
| the harness, the dispatch smoke driver, the gate | the shared helper of decision 10 | `packages/workflow/src/dsy_workflow/harness/cluster.py` | `async make_deployed_current(client, context, timeout_s=POLLERS_S) -> CurrentBuild`, where `CurrentBuild` is a frozen dataclass of `current: str`, `deployed: tuple[str, ...]` and `made: str \| None` (decision 19): `current` is the build current when the helper returns, `deployed` the deployed builds it listed, and `made` the build it made current, or `None` when it wrote nothing; raises the harness's `Refused` when the current build is not deployed, or when no build is current and the deployed builds are not exactly one | in `dsy_workflow` from R.1 |
| every driver | a deadline on a forward | `packages/clusterkit/src/dsy_clusterkit/__init__.py` | `Forward.open(timeout_s: float = UP_S)`, the default unchanged | from 0.1 |

Recipe contract (replaces the stub's exit 3):

| Exit | Meaning |
| --- | --- |
| 0 | every row ok |
| 1 | a row failed, or the 300 s budget ran out (`FAIL budget`) |
| 2 | usage: unsupported preset (D1), a host tool missing, or `cluster-verify`'s own exit 2 passed through |
| 4 | refused: no cluster `dsy`, or one started for another preset (passed through from `cluster-verify`), or the lock could not be taken within its 900 s wait (decision 18) |

Summary, one line per row in `cluster-verify`'s format so both read alike, then a count line:

```
ok cluster-verify ci: 10 ok, 0 failed
ok api dispatch and control /readyz ready
ok broker 0 dead letters before the job
ok temporal namespace dsy, build exit-a current (made current), deployed exit-a
ok placement 3 pools
ok job-submit accepted 0b6e2f0a-...
ok job-run succeeded, build ran (attempt 1)
FAIL job-result echo blocks differ: <first differing key>
skip job-aggregate after job-result failed
ok dead-letters 0, no rise
smoke ci: 8 ok, 1 failed, 1 skipped, 94 s
```

Every printed row counts in exactly one of `ok`, `failed` and `skipped`.
A row that D4 or a failed earlier job row stops prints `skip <row> <reason>`.
Postgres and observability have no row (section 1.2), so they print nothing and count nowhere.

## 3. Lanes

| Lane | Worker count | Owns (path globs, exclusive) | Issues | Needs |
| --- | --- | --- | --- | --- |
| 0 | 1 | `packages/acceptance/*`, `packages/acceptance/src/dsy_acceptance/*.py`, `packages/acceptance/tests/*.py`, `scripts/smoke.sh`, `packages/clusterkit/src/dsy_clusterkit/__init__.py` (`Forward.open` only), `packages/clusterkit/tests/test_clusterkit.py`, root `pyproject.toml` (the `dsy-acceptance` lines only), `uv.lock` (rerun rule); `packages/acceptance/*` includes the package's `pyproject.toml` and with it the whole dependency set (decision 20) | 0.1 | none |
| C | 1 (the same worker) | `packages/acceptance/src/dsy_acceptance/clients/**`, `packages/acceptance/tests/clients/**`; no dependency line, because 0.1 declares every one the clients import (decision 20) | C.1 | lane 0 |
| R | 1 (the same worker) | `packages/workflow/src/dsy_workflow/harness/cluster.py`, `packages/workflow/src/dsy_workflow/versioning.py` (`set_current` only), `packages/workflow/tests/harness/test_make_current.py`, `packages/dispatchapi/src/dsy_dispatchapi/smoke/__init__.py`, `packages/dispatchapi/pyproject.toml` (the `cluster` extra only), `uv.lock` (rerun rule) | R.1, R.2 | lane 0; R.2 also C.1 |
| G | 1 (the same worker) | `packages/acceptance/src/dsy_acceptance/smoke/**`, `packages/acceptance/tests/smoke/**`; no dependency line, because 0.1 declares every one the gate imports (decision 20) | G.1, G.2 | lane 0, C.1, R.1; G.2 also R.2 |

Shared-file rules: `uv.lock` is touched by 0.1 (the new package with its full dependency set, decision 20) and R.2 (the driver's new dependency), and by no C or G issue, since `packages/acceptance/pyproject.toml` is lane 0's alone; a conflict is never resolved by hand, `uv lock` is rerun after rebase (`method.md:84`).
No other file is shared: R owns the dispatch smoke driver alone, and the gate's lanes never edit it.

Departures from the method, stated so that the captain approves them knowingly:

- 0.1 declares the acceptance package's full dependency set (decision 20) before C.1 and G write the code that imports it, where `method.md:84` says a dependency lands in the PR that needs it.
  Why: each package's `pyproject.toml` is owned by one lane (`method.md:83`), and C and G own only their own modules, so an added dependency in C.1 or G would be an out-of-lane edit (`method.md:94`).
  Lanes 0, C, R and G are one worker in sequence, so declaring the set early costs nothing, and the 0.1 wheel test resolves only declared dependencies, so a later undeclared import fails there rather than hiding in the dev venv.

## 4. Issues

Each issue below was filed on 2026-11-20 from the [lane issue template](../../../.github/ISSUE_TEMPLATE/lane-issue.md), and its body holds the block that stood here: scope, owns, consumes and produces, acceptance criteria, verifier, and needs and blocks as links.
0.1, C.1, G.1 and G.2 are sub-issues of #17; R.1 is a `revisit` child of #6 and R.2 a `revisit` child of #24.

- [#539](https://github.com/AndoNorth/disyard/issues/539) 0.1 Package skeleton, wrapper and forward deadline
- [#540](https://github.com/AndoNorth/disyard/issues/540) C.1 Clients
- [#541](https://github.com/AndoNorth/disyard/issues/541) R.1 Make the deployed build current (revisit of #6)
- [#542](https://github.com/AndoNorth/disyard/issues/542) R.2 Driver onto the shared helper and client (revisit of #24)
- [#543](https://github.com/AndoNorth/disyard/issues/543) G.1 Boundary rows
- [#544](https://github.com/AndoNorth/disyard/issues/544) G.2 Job rows

## 5. Order, stubs and spikes

Lane 0 (0.1) merges first, alone (`method.md:55-57`); then C.1 and R.1, then R.2, G.1 and G.2, one worker in that order.
No stubs: every dependency is merged.
No spikes: the job path is measured (row 12 of #24).
No stub contract test exists for `scripts/smoke.sh` today (grep finds none), so 0.1 adds the T0 test of the exit mapping instead.

## 6. Test delta

- T0: the summary format and exit mapping, the wrapper with fake tools, the forward deadline, each client against a canned answer, each row's verdict against a canned answer, the shared helper's outcomes, the moved code's existing tests in `dsy_workflow` and `dsy_dispatchapi`.
- T2: `just smoke` itself, plus the one manual placement check of G.1; no pytest at T2 in this pass (decision 14).
- Untested: telemetry (decision 11), cold start on a CI runner (decision 13), a dead pool naming itself on row 1 (section 8).

## 7. Exit test

Run by a worker who did not write the lanes, on a clean export of `main`, under the lock.
The export has no git checkout, so every `scripts/tilt/run.sh ci` sets `DSY_BUILD_ID=exit-a` (`deploy/workflow/Tiltfile.module:15-17`), the same value for every cycle.
Each row's output is pasted in the PR that records the run and summarised in Closure.

| Row | Command | Expected | Evidence |
| --- | --- | --- | --- |
| 1 | `just ci` | exit 0 | output in the PR |
| 2 | `just nuke`, `just up`, `DSY_BUILD_ID=exit-a scripts/tilt/run.sh ci` | cluster up from no cluster, Tilt `SUCCESS` | output in the PR |
| 3 | `just smoke` ten times in a row | ten consecutive exit 0 with every row `ok`; the first run's row 4 says it made `exit-a` current; each elapsed under 300 s, and the first is the measured local run of decision 13 | the ten summaries in the PR, the elapsed figures in Closure |
| 4 | two fresh cycles, each `just nuke`, `just up`, `DSY_BUILD_ID=exit-a scripts/tilt/run.sh ci`, `just smoke` (decision 12) | both `just smoke` exit 0, row 4 made `exit-a` current, and row 7 says the build ran | the two summaries in the PR, the elapsed figures in Closure |
| 5 | `DSY_PRESET=dev just smoke` | exit 2 with the preset reason | output in the PR |
| 6 | `just nuke`, then `just smoke` | exit 4, `refused: no kind cluster named dsy, start one with: just up` | output in the PR |

## 8. Parallelism and cost

- Maximum parallel workers: 1, in every phase; the issues are ordered (section 5).
- Host constraints: the cluster is single-owner, so the T2 rows of G.1 and G.2 and the exit test queue for the lock, and `ci` needs 12,032 MiB of the 20 GiB host beside other containers (`deploy/presets/ci.yaml:8`).
- CI cost, estimates: no new workflow, and the new T0 tests run in seconds.
- Estimates, not measurements, in worker-days: 0.1 (1), C.1 (1), R.1 (0.5), R.2 (0.5), G.1 (1.5), G.2 (1.5), exit test (1), about 7 worker-days and 7 days elapsed with one worker.
  The main sources of slip are fresh-cluster failures of `tilt ci` (https://github.com/AndoNorth/disyard/issues/528) and cluster lock contention.

Risks:

- `cluster-verify` has never been timed; row 1's 90 s deadline is an estimate, measured first in G.1.
- A dead pool worker makes row 1 end at its 90 s deadline naming the last check line, not the pool, because each pool's readiness rule waits up to 300 s (`deploy/workers/compile/module.yaml:16-24`); shortening that wait is a change to #10's modules, not taken in this pass.
- A cold first compile is the budget's swing factor (epic risks); 66 s is one measurement.
- Row 4 passes on whichever build is current as long as it is still deployed.
  After a redeploy beside a current build, both builds are deployed and the old one stays current, so the job runs on the old build; the row line names the current and the deployed builds from the helper's result (decision 19), so a reader sees which build ran, and making the new build current is the rollout's job (`deploy/workflow/README.md:26-28`), not the gate's.
  The gate is not purely read-only: the helper writes only when no build is current and exactly one is deployed, refuses a current build that is no longer deployed, and never overwrites a build made current during its poller wait.
- Open intake issues may make the job late, not wrong: https://github.com/AndoNorth/disyard/issues/520 (reconciler left rows unpublished for about 195 s) would push row 7 past the budget if the single job's publish takes the reconciler path.
- Fresh `ci` clusters fail `tilt ci` with `cluster did not pass liveness check` in about 4 of 20 cycles (https://github.com/AndoNorth/disyard/issues/528), so exit rows 2 and 4 can fail before the gate runs.
- `scripts/tilt/run.sh` takes no lock, so a deploy can overlap a gate run; the gate cannot fix that, #2 can.
- No runner has deployed the services, so the gate's fit on a CI runner is unknown until pass 2 (decision 13).

## 9. Closure (filled at close)

Run on 2026-11-20 and 2026-11-21 by a worker who did not write the lanes, on a clean `git archive` export of `main` at `1c74d1e` under `/tmp`.
Host: WSL2 with 20,002 MiB `MemTotal` and 8 CPUs, no other cluster, and one other container (`open-webui`) that was running before and after and was not touched.
Every row held `flock /tmp/dsy-cluster.lock` for its whole sequence, and every `scripts/tilt/run.sh ci` set `DSY_BUILD_ID=exit-a`.
Real command output is in the pull request that records the run.

| Row | Result | Evidence |
| --- | --- | --- |
| 1 | pass | `just ci` exit 0 on the full path in 3,866 s: 3,305 unit tests and 775 integration tests passed, then `nix flake check` |
| 2 | pass | `just nuke` 13 s, `just up` 150 s, Tilt `SUCCESS. All workloads are healthy.` in 697 s |
| 3 | pass | ten consecutive exit 0 with every row `ok`; the first run's row 4 reads `build exit-a current (made current), deployed exit-a` |
| 4 | pass | both cycles exit 0, row 4 reads `build exit-a current (made current)` and row 7 reads `succeeded, build ran (attempt 1)` |
| 5 | pass | exit 2, `usage: smoke needs preset ci, the only preset that deploys the pool workers, not dev` |
| 6 | pass | exit 4, `refused: no kind cluster named dsy, start one with: just up` |

Elapsed figures are the seconds on each run's `smoke ci:` summary line; the `just smoke` wall clock, which adds `uv` start-up, is in brackets.

- Row 3, in order: 96 (100), 24 (37), 24 (33), 24 (28), 24 (28), 23 (27), 24 (27), 24 (28), 23 (27), 24 (28).
  The first, 96 s on a deploy finished a minute earlier, is the measured local run of decision 13.
- Row 4: cycle 1 69 (79), cycle 2 69 (80), each on a deploy that had just finished.

Departures and failures on the way, none in the gate:

- Row 1 failed on the first attempt with one integration test out of 775, `packages/dispatchapi/tests/control/test_retrier.py::test_request_during_outage_delivered_after`, which saw a signal twice.
  It reproduced 1 time in 10 under CPU load and 0 times in 10 on an idle host: the test's 1 s call timeout lets a signal the restarted server already applied be retried, so delivery is at least once as designed while the test asserts exactly once.
  The captain chose to rerun row 1, which passed.
- Row 4 cycle 1 failed on the second attempt at the deploy, with `cluster not ready` and `cluster connection failed`, the failure of https://github.com/AndoNorth/disyard/issues/528.
  etcd requests took up to 18.9 s, kube-controller-manager and kube-scheduler lost leader election three times, and host I/O pressure was 79 % (60 s average) while four images were pulled at once, with CPU pressure near 1 %.
  The captain chose to rerun row 4, whose two cycles then passed.
- Finished with `just nuke` (row 6); `MemAvailable` afterwards was 17,618,624 kB.

Closure addenda, one dated line each, added after close when a `revisit` child issue is filed against this epic:

- 2026-11-26: pass 2 closed its exit test, see [section 10](#10-pass-2-closure).

## 10. Pass 2 closure

Pass 2 delivered level 4, `just e2e`, and the [test ladder](../../acceptance-ladder.md).
The exit test was run on 2026-11-25 and 2026-11-26 by the worker of the live validation task, under `/tmp/dsy-cluster.lock`, on a host with 20,002 MiB `MemTotal` and 8 CPUs, with preset `ci` and `DSY_OBS=on`.
The captain closes epic #17 when this closure is accepted, and it is not closed by this document.

### Baseline B0 (before the live validation)

Recorded on a clean `git archive` export of `main` at `5d6853f2f6353c985f0e2a7394beb08df05d7332`, with `DSY_BUILD_ID=exit-a`.

| Step | Result |
| --- | --- |
| `just ci` | exit 0, 3,182 s |
| `just nuke`, `DSY_OBS=on just up`, `scripts/tilt/run.sh ci` | 13 s, 58 s, 308 s, Tilt `SUCCESS. All workloads are healthy.` |
| `just cluster-verify` | exit 0, 10 `ok`, 0 failed, 27 s |
| `just smoke` three times | exit 0 each, 11 `ok`, `smoke ci:` 75, 27 and 27 s (wall 80, 38, 38 s). The second and third show `build hit the cache (attempt 0)`, and row 11 reads `4 scrape jobs up, logs of 5 services, trace of 3 services, 7 profiles` |
| `pytest packages/obs/tests/catalogue -m cluster` | 1 passed with `DSY_OBS_PROMETHEUS_URL` set to a forward of Prometheus, and 1 skipped without it |
| Prometheus `ALERTS{alertstate="firing"}` | only `DsyWatchdog` |

The smoke gate prints a total and no seconds for each row, so the record holds totals.
`just up` failed once before this, in 12 s, because an orphan RabbitMQ container of an integration run (`dsy-20261124T185046Z-0-833639-16`, 28 hours old, its owner process gone) held the ports 19000 and 19001.
It was removed and `just up` was run again.

### Defects the live run found in the merged scenario code

The first live `just e2e` on B0 ended with 6 of 9 scenarios ok, H1 and H2 failed and N6 skipped.
Each of these was invisible to the fake driven tests, which had modelled the platform as the code assumed it was.

1. H2 could not see H1's job: the `acceptance_job` fixture lived in `test_happy.py`, and H2 also took a counter baseline that nothing produced. The fixture moved to `conftest.py` and H1 takes the baseline before it runs.
2. H1 asserted that polling saw every status, but `admitted` lasts under a poll. The stored lifecycle events prove each state, and the samples now only have to follow the lifecycle in order.
3. H1 and the aggregate check read `task.requested` events from the event table, which does not store them: the event is the input of the `run_task` activity, so the live platform reads it from the Temporal history. The aggregate reads one `index` input and not the results, so the check reads the index and compares the result references in it.
4. N1 asserted `task.succeeded` for chain a's compile, which a second run on one deploy meets as a compile cache hit (`task.skipped`).
5. H2 asserted a result ready event in the workflow history, where the history carries the task requests and `job.accepted`, and the result ready events only reach the event table. It now asserts a task request in the history for each simulate and for the aggregate. Its history read also called `asyncio.run` inside the polling loop and now runs in a thread of its own.

The fixes are in the branch of this pull request and are the only code changes of the exit test.

### Exit test

Run on the export of the branch at `11f4def3dbcdf188cf5266d92c897f5884b4259a` (`main` at `5d6853f` plus the fixes above), which is why the export is not `main` itself.

| Step | Result |
| --- | --- |
| `just ci` | exit 0, 3,143 s |
| First cycle: `just nuke`, `DSY_OBS=on just up`, `scripts/tilt/run.sh ci` (`DSY_BUILD_ID=exit-d`), `just cluster-verify` | 24 s, 55 s, 278 s, 25 s, Tilt `SUCCESS`, 10 `ok` |
| `just smoke` | exit 0, 11 `ok`, 73 s, `build ran (attempt 1)` |
| `just e2e` | exit 0, 9 `ok`, scenarios 319 s, wall 360 s |
| `just e2e --loop 10` | ten passes `ok` on one deploy and one lock hold, 2,055 s, `e2e loop: 10 ok, 0 failed` |
| Second cycle: `just nuke`, `just up`, Tilt (`exit-d2`), `just cluster-verify`, `just smoke`, `just e2e` | 22 s, 48 s, 264 s, 25 s, smoke 11 `ok` in 73 s, `just e2e` 9 `ok`, scenarios 316 s, wall 349 s |

The seconds of each scenario are in [the ladder](../../acceptance-ladder.md#measured), and the budget of 600 s for the scenarios stays.
Before the exit test, a full `just e2e` on the B0 deploy after the fixes also passed once (9 `ok`, scenarios 173 s).

### Cost of the sessions

Sampled every 5 s on the host for the whole run, which is about 4 hours of lock.
Memory is the host `used` figure of `free`, which includes the kind node containers.

| Phase | Wall seconds | Peak host memory used (MiB) | Lowest `MemAvailable` (MiB) | Peak CPU of 8 cores | Peak load average (1 min) |
| --- | --- | --- | --- | --- | --- |
| `just ci` (twice) | 3,182 and 3,143 | 4,602 and 4,544 | 15,399 and 15,457 | 99 percent | 13.3 and 10.9 |
| `just up` | 58 and 55 | 3,443 and 3,216 | 16,558 and 16,785 | 50 percent | 4.2 and 3.1 |
| `scripts/tilt/run.sh ci` | 308 and 278 | 5,607 and 5,599 | 14,395 and 14,402 | 66 percent | 6.1 and 5.3 |
| `just smoke` | 77 to 80 | 6,038 | 13,963 | 29 percent | 3.2 |
| `just e2e`, one run | 173 to 360 | 6,305 to 6,659 | 13,342 to 13,696 | 41 percent | 2.3 to 3.5 |
| the ten pass loop | 2,055 | 6,683 | 13,318 | 35 percent | 3.6 |

- The whole run peaked at 6,683 MiB used and never went below 13,318 MiB available of 20,002 MiB.
  The 15,488 MiB that `ci` with the stack needs is the preset's host requirement, and the measured use of the host while it ran was less than half of it.
- Swap use grew from 1,037 to 1,240 MiB over the run, and mean CPU over any phase was 11 to 38 percent.
- Disk use of the host volume grew from 360 to 388 GiB over the run, which includes the image pulls of three bring-ups and the Nix store builds of two `just ci` runs.
- The raw samples and the output of every step are with the task record, not in the repository.

### What was learned

- The e2e is flake free over the 10 passes: no scenario failed, and the one pass time spread was 172 to 179 s of scenarios.
- N1, N4 and C1 cost about three times as much on a fresh deploy, and the same on a second fresh cycle, so the fresh deploy numbers are the ones a first run meets.
- `DsyAdmissionDeadLettered` fires after `just e2e`, because N4 dead letters two poison events on purpose and the rule is an increase over 10 minutes. It resolves by itself, so the "only the watchdog is firing" check belongs before the e2e and not after it.
- The catalogue test is skipped without `DSY_OBS_PROMETHEUS_URL`, and a run that does not set it passes by skipping.

### CI decision

No CI job runs the e2e, from the numbers above and the captain's decision Q9, recorded in [the ladder](../../acceptance-ladder.md#where-it-runs).
A nightly job on `ci` with the stack off that skips H2 is the one option left open and needs the captain's answer before any workflow changes.

### Not covered

- Two compile pods on different nodes with overlapping attempts (decision Q1): `ci` has one compile node, so it is for a local fixture or the load test of #14 and #16.
- Finishing from the checkpoint after a pause, and a resume with a patched bundle: waits for the checkpoint epic #18.
- Row 4 of the observability exit test (the worker probes), and its rows 2, 3, 8 to 16, which this run did not exercise, see section 9 of [the observability epic](18-observability.md).
- Every defect above was found by the live run and not by a lower level: the fake driven tests of the scenarios now model the stored events as they are, but a contract test that the event table holds no `task.requested` event does not exist.
