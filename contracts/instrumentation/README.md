# Instrumentation contract

Owner epic: #13 (observability), which took the contract over from #4 (job event envelope and state propagation).
Version: 9
Consumers: every component that emits a metric, a log line or a span, and #14, #15, #16 and #17.

This contract pins the rules for metrics, labels, log fields and traces, and the platform catalogue in `metrics.yaml`.
Every metric a dashboard or a rule reads is in the catalogue: a `dsy_` name under `metrics`, or a third-party series under `external`.

## Metric names

- A name is `dsy_` followed by lower-case words and digits joined by underscores.
- A counter ends in `_total`, and a gauge or a histogram never does.
- A metric with a unit ends in that unit, in base units (`bytes`, `seconds`, `ratio`), before the `_total` of a counter.
- A histogram declares its bucket bounds in `metrics.yaml`.

## Labels

- A label is never an unbounded identifier.
  The denylist is `x-label-denylist` in [metrics.schema.json](metrics.schema.json), and it holds the job id, task id, attempt, event id, trace id, `traceparent` and the names that spell them differently.
- Every label declares its bounded set of values in `metrics.yaml`, either as `values` or as `values_from`, the repository directory whose entry names are the values.
  The value sets of the shared labels are below, and a label of one metric declares its own set beside it in `metrics.yaml`.
- The priority class and the job class are the context attributes that are allowed as labels, because each is a configured set.
  They are declared like any other label.
- `le` and `quantile` are reserved.

| Label | Values |
| --- | --- |
| `pool` | `compile`, `simulate`, `aggregate` |
| `exit_class` | the classes of `contracts/workload/exit-classes.yaml`, of every pool |
| `job_class` | `short`, `long`, the job classes of `contracts/tenancy/tenancy.yaml` |
| `priority_class` | `standard`, the priority classes of `contracts/tenancy/tenancy.yaml` |
| `outcome` of `dsy_workflow_job_seconds` and `dsy_workflow_jobs_total` | the terminal statuses of `contracts/status/status.yaml` |
| `verdict` of `dsy_placement_decisions_total` | `placed`, `unschedulable` |
| `scope` | `global`, `open`, the two caps of the tenancy profile |
| `component` | `dispatch`, `admission`, `workflow`, `placement`, `compile-worker`, `simulate-worker`, `aggregate-worker`, `state-inputs` |
| `row` | `1` to `11`, and `run` for the whole run of the smoke gate |
| `verdict` of `dsy_smoke_row_verdict` | `ok`, `FAIL`, `skip` |

## Log fields

Version 4 renames the log fields, a breaking change from version 3.
A structured log line is one JSON object with `ts` (RFC 3339, UTC), `level`, `component` and `msg`, and, when known, `tenant`, `job_id`, `task_id`, `attempt_id`, `trace_id`, `span_id`, `event_type`, `cloudevent_id`, `pool` and `exit_class`.
A line carries no other field.
A context attribute of the event maps to a log field as follows.

| Context attribute | Log field |
| --- | --- |
| `tenant` | `tenant` |
| `jobid` | `job_id` |
| `taskid` | `task_id` |
| `attempt` | `attempt_id` |
| `traceparent` | `trace_id` and `span_id`, the trace id and the parent id it holds |

`traceparent` is not a log field: an emitter passes the event's value as it is, and the helper derives `trace_id` and `span_id` from it.
`cloudevent_id` is the CloudEvents `id`.
The stored event key keeps the name `event_id`, which is the pair `<source>#<id>`, so the two names never mean the same thing.

## Traces

- The trace context is the `traceparent` attribute of the event, as the W3C trace context defines it.
- A stage starts a span per event it handles, parented from the `traceparent` of that event, and an event the stage emits carries the `traceparent` of that span.
- A span carries the context attribute names as attributes, not the log field names, and never puts them in a metric label.
- There is no promise of one trace for a job that lasts days, and a stage that resumes after a pause starts a span linked to the earlier one.

## The catalogue

`metrics.yaml` holds every `dsy_` name under `metrics`, with its type, unit, help, labels and, for a histogram, its buckets.
The buckets are pinned here, and an emitter passes them to its runtime as they are; a change to them is a contract-change PR.
The top finite bucket of `dsy_workflow_job_seconds` is 604,800 s, the 7-day maximum of a job, so a full-length job does not land in `+Inf`.

| Emitter | Names |
| --- | --- |
| the event serializer and reader | `dsy_event_*` |
| the broker client | `dsy_broker_*` |
| admission | `dsy_admission_*` |
| dispatch and control | `dsy_dispatch_*`, `dsy_control_*` |
| workflow | `dsy_workflow_*` |
| placement | `dsy_placement_*` |
| the worker pools | `dsy_worker_*` |
| the smoke gate, pushed once per run | `dsy_smoke_*` |
| the state inputs exporter | `dsy_state_*` |
| the observability helper | `dsy_obs_*` |

The event metrics are asserted by the events lane and the upgrade metric by the compatibility lane, in their own tests.
The broker counters live in the in-process registry of `dsy_events.metrics`, which every process that loads it exports; [contracts/broker/README.md](../broker/README.md) describes them, and `packages/broker/tests/test_reasons.py` holds the `reason` values of `dsy_broker_dead_letter_total` equal to the application codes of `contracts/broker/reasons.yaml`.

A state input of `contracts/state/inputs.yaml` of kind `sql`, `sql_labelled` or `invariants` is the gauge `dsy_state_<input name>`, with `_bytes` or `_seconds` appended when its unit is one of those and its name does not already end in it.
The inputs of kind `store` are not catalogued, because the store's own metrics carry the same figures.
A name with no emitter is not catalogued, so `dsy_workflow_paused_jobs` and `dsy_workflow_replay_failures_total` are not; `dsy_admission_paused_jobs` is the one paused gauge.

An entry marked `conditional: true`, under `metrics` or `external`, is legitimately absent from a healthy idle run.
Its series is not exported until a fault or an unusual event happens, or the platform does not produce it on the local cluster.
A consumer that expects every catalogued series to have a sample, such as the live catalogue check, skips the conditional entries.

### Third-party series

`external` holds each third-party series a dashboard or a rule reads, with its type, help, the scrape job that collects it and the labels the rules group by.
A third-party series keeps its own name, so the `dsy_` naming rule does not apply to it, and its labels are held to the denylist.
The Temporal, kube-state-metrics, cAdvisor, kubelet, SeaweedFS and observability stack series that the dashboards and rules read are catalogued, grouped by their scrape job; a new one is added by a contract-change PR once it is confirmed on its pinned version.

## Loader

`contracts/instrumentation/check.sh <file>` validates a metrics file.
It exits 0 when valid, 1 with `reason: <code>: <detail>` on stderr when not, and 2 on usage.

| Reason | Fails when |
| --- | --- |
| `schema-violation` | the file does not match the schema, which includes an unknown type, a reserved label name, an empty `values` list and an external series without its scrape job |
| `bad-metric-name` | a name breaks the naming rule, or a histogram has no buckets |
| `denied-label` | a label of a metric or of an external series is on the denylist |
| `undeclared-label-values` | a label declares neither `values` nor `values_from` |
| `unknown-values-source` | `values_from` is not a directory of the repository |

## Vectors and the loader test

`vectors/valid/*.yaml` must pass, and `vectors/invalid/<reason>/*.yaml` must fail with that reason.
`scripts/verify/cluster/lib/vectors.sh contracts/instrumentation contracts/instrumentation/metrics.yaml` runs them and also loads the pinned file.
`packages/events/tests/test_instrumentation.py` runs the same loader test inside `just ci`.

## Changing it

The rule for changing this contract once pinned is in [Changing a contract](../../docs/contracts.md#changing-a-contract).
