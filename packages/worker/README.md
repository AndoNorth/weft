# dsy-worker

The pool workers: one activity worker per pool (compile, simulate, aggregate) that serves `run_task` of the activity contract by running one child process at a time.
The contracts it serves are pinned in `contracts/activity/README.md` and `contracts/temporal/README.md`, and the worker detail is drawn in `docs/architecture/18-pool-worker.drawio`.

## State

Delivered:

- `dsy_worker.read_request`: the one place the worker reads its task request, held to the worker stage of `contracts/stages/stages.yaml`.
- `dsy_worker.config`: the configuration of `python -m dsy_worker --pool <pool>`, read from the environment only, which exits 2 on a missing or malformed variable.
- `dsy_worker.pools.Context`: what a task path runs with.
- `dsy_worker.testing.contract_cases`: a succeeding and a failing task input per pool over a seeded store, for `dsy_workflow.testing.activity_contract`, with the class each failing input fails with in `FAILS`.
  It builds the workload library, so it runs in the repository's dev environment only.
- `dsy_worker.runner`: `Child`, the process group runner.
- `dsy_worker.pools.{compile,simulate,aggregate}`: `run`, the task path of each pool.
- `dsy_worker.activity`: `run_task`.
- `dsy_worker.service`, `dsy_worker.__main__` and `dsy_worker.probe`: the service, its command line and the egress probe.

No module has a stub, so every `STUBBED` is empty, and `tests/test_stubs.py` fails on a name that raises the stub error without being listed there.

## Extras

Each pool image installs one extra beside the core: `compile` adds `dsy-compile` and `uv`, `simulate` adds `dsy-runtime`, and `aggregate` adds `dsy-aggregate`.
The core depends on `dsy-workflow` for the activity models, so every image also carries its chain.

## Commands

```sh
nix develop -c uv run --frozen pytest packages/worker -q -rs
nix develop -c uv run --frozen pytest packages/worker -v -m integration -k contract_cases
nix develop -c uv export --frozen --package dsy-worker --extra compile
```
