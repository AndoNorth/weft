# S8 CI-S1: the integration tier under xdist on a runner

## Question

Do two xdist workers, each holding one of the two T1 lock files, cut the integration time of the `artifacts` shard by at least 30% without a failure that `-n0` does not show?

## Decision

Fail.
No variant met both halves of the pass line.
Plain `-n 2` saves no time and crashes a worker in every run.
Splitting the `pair` tests out saves about 26% and still errors in every run.
No follow-up issue on `dsy_itest` lock handling is filed.

## Method

The workflow `.github/workflows/ci-s1-xdist.yml` runs `docs/delivery/spikes/S8/code/xdist-integration.sh` on `ubuntu-latest` through the same nix, build-cache and uv-cache setup as the `test` job of `ci.yml`.
Each of three variants ran 5 times, each run on its own runner, in one workflow run: https://github.com/AndoNorth/disyard/actions/runs/46183371249
The layout of #832 is unchanged, and the shard is `artifacts`, selected by `scripts/ci-shards.sh artifacts`.

| Variant | What runs |
| --- | --- |
| `n0` | `pytest -m integration -n0`, the layout CI uses today |
| `n2` | `pytest -m integration -n 2 --dist worksteal` |
| `n2split` | `-n 2` on `integration and not pair`, then `-n0` on `integration and pair`, because a pair test needs both lock files |

## Numbers

Seconds of pytest wall time per run, sorted.

| Variant | Runs | Median | Mean | Against `n0` median |
| --- | --- | --- | --- | --- |
| `n0` | 431.8, 491.1, 522.0, 534.8, 542.8 | 522.0 | 504.5 | |
| `n2` | 439.0, 440.7, 519.3, 543.0, 572.0 | 519.3 | 502.8 | -0.5% |
| `n2split` non-pair part | 209.5, 224.3, 238.2, 239.1, 247.4 | 238.2 | 231.7 | |
| `n2split` pair part | 123.8, 145.8, 148.0, 148.5, 149.4 | 148.0 | 143.1 | |
| `n2split` total | | 386.2 | 374.8 | -26.0% |

The pass line is 30%, so `n2split` misses it by 4 points even before its failures count.

## Pass set and failures

`n0`: 158 tests collected, 0 failures or errors in all 5 runs.
The issue names 172 tests, and the shard selects 158 under `-m integration` at this commit, so the count in the pass line is stale.

`n2`: 158 tests, and in every run one test errors on setup because its worker crashed:

| Runs | Test |
| --- | --- |
| 1, 4, 5 | `packages/eventstore/tests/test_chunks.py::test_duplicate_into_a_compressed_chunk_inserts_nothing` |
| 2, 3 | `packages/migrate/tests/test_runner.py::test_two_runners_serialize_on_the_lock` |

The JUnit reports carry only the crash message, so the cause of the crashes is not established here.

`n2split`: the pair part passes 13 of 13 in every run.
The non-pair part errors on setup in every run, 2 to 7 tests, with `ContainerError: one container at a time, stop the running one first`, in `packages/worker/tests/activity/test_run_task.py` and `packages/storecheck/tests/test_store.py`.
Those tests start two containers without carrying the `pair` marker.
In the full `n2` runs the same tests did not fail with that error, because every worker took both lock files there, which serialised the whole run.

## What this says about the design

With the lock handling as it is, a collected `pair` test makes the `t1` fixture of every worker ask for both files, so the workers queue on each other and `-n 2` gains nothing.
Separating the pair tests gains time, but only if every test that needs two containers carries the marker, which three of them do not.
A lock scheme for xdist would need a fix of those markers, an explanation of the two worker crashes, and a new 5-run measurement before it could pass this line.

## Files

- `.github/workflows/ci-s1-xdist.yml`, run by hand with `workflow_dispatch`
- `docs/delivery/spikes/S8/code/xdist-integration.sh`
