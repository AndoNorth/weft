# Runbooks

The one place that links to everything needed to bring the system up, prove it works, triage a failure and tear it down.
Start with [dev setup](../dev-setup.md) when the machine is new, then come here.

## The runbooks

| Need | Go to |
| --- | --- |
| Bring up, run a job, check health, tear down, and the rules of the one cluster | [Operator runbook](operator.md) |
| Cut a release, and what each refusal of `just release` means | [Release runbook](release.md) |
| Which check proves what, what it costs and when to run it | [Validation matrix](validation-matrix.md) |
| The levels of testing, their rules, budgets and gate order | [Test ladder](../acceptance-ladder.md) |
| A symptom, and the dashboard and query that narrows it down | [Triage by symptom](triage.md) |
| An alert is firing | [Alert response](alerts.md), one entry per rule |
| What a failure looks like and how to recover, run on a cluster | [Failure drills](drills/README.md) |

## First hour

1. [Dev setup](../dev-setup.md): host prerequisites, `nix develop -c just doctor`.
2. [Bring up](operator.md#bring-up), with the observability stack on if alerts and dashboards are wanted ([Observability on](operator.md#observability-on)).
3. [Prove it](validation-matrix.md#the-smoke-rows): `nix develop -c just smoke`.
4. [Tear down](operator.md#tear-down) and [confirm nothing is left](operator.md#confirm-nothing-is-left-behind).

## Per-component material

The runbook sections that already live next to a component stay there.

| Component | Where |
| --- | --- |
| Object store: full disk, credential rotation, lifecycle worker | [deploy/objectstore](../../deploy/objectstore/README.md#runbook) |
| Observability stack: what runs, following one job | [deploy/obs](../../deploy/obs/README.md) |
| Prometheus, its scrape jobs and the rule tests | [deploy/obs/prometheus](../../deploy/obs/prometheus/README.md) |
| Grafana, datasources and access | [deploy/obs/grafana](../../deploy/obs/grafana/README.md) |
| Dashboards and what each shows | [deploy/obs/grafana/dashboards](../../deploy/obs/grafana/dashboards/README.md) |
| Broker: credentials, the host forward and the dead-letter tool | [deploy/rabbitmq](../../deploy/rabbitmq/README.md) and [packages/broker](../../packages/broker/README.md) |
| Dispatch and control API: ports, readiness and the smoke driver | [deploy/dispatchapi](../../deploy/dispatchapi/README.md) |
| Admission | [deploy/admission](../../deploy/admission/README.md) |
| Placement | [deploy/placement](../../deploy/placement/README.md) |
| Workflow worker and its builds | [deploy/workflow](../../deploy/workflow/README.md) |
| Pool workers | [deploy/workers](../../deploy/workers/README.md) |
| Temporal and its bootstrap | [deploy/temporal](../../deploy/temporal/README.md) |
| App database | [deploy/appdb](../../deploy/appdb/README.md) |
| The WSL2 host | [Cluster host guide](../cluster-host.md) |

## Reference

| What | Where |
| --- | --- |
| Metrics the platform exports | [contracts/instrumentation](../../contracts/instrumentation/README.md) |
| API routes, bodies and reason codes | [contracts/api](../../contracts/api/README.md) |
| Dead-letter reasons and their recovery | [contracts/broker/reasons.yaml](../../contracts/broker/reasons.yaml) |
| Job statuses | [contracts/status](../../contracts/status/README.md) |
| Why the system has this shape | [docs/architecture](../architecture/) |

## Keeping these pages true

A command in a runbook is copied from a recipe or a script, never from memory, so when a recipe changes its runbook changes with it.
Each alert rule carries a `runbook_url` that points at its entry in [alert response](alerts.md), and the rule tests fail when a rule has none, when its link does not name its own entry, or when an entry has no rule.
