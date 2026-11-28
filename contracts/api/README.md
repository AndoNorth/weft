# API contract

Owner epic: #24 (dispatch and control API).
Version: 3, in [VERSION](VERSION).
The [Consumers](#consumers) section names who reads each part.

The dispatch and control API is the front door of the platform: a submitter sends a batch of jobs in one call and gets an answer per job, and an operator cancels, pauses, resumes or terminates a job.
This directory pins the routes, the bodies, the reason codes, the control table and the job fingerprint.
The schemas under [schemas/](schemas/) are generated from the models of `dsy_dispatchapi.models` by `python -m dsy_dispatchapi.gen` and never edited by hand.
The tenants and priority classes that the API accepts live in the [tenancy contract](../tenancy/README.md), the statuses and moves of a job row in the [status contract](../status/README.md), and the events the API writes in the [stage contract](../stages/README.md).

## Routes

[routes.yaml](routes.yaml), with schema [routes.schema.json](schemas/routes.schema.json).

The service listens on two ports, `dispatch-api` for uploads, batch submit and batch reads, and `control-api` for control and the job status read.
Each route is on one listener, and `/healthz` and `/readyz` are on both.
Every path under `/v1/tenants/{tenant}` answers 404 `UNKNOWN_TENANT` before any body is read when the tenant is not in the tenancy profile, so a call never sees another tenant's job.
`/readyz` answers 200 `{"status": "ready"}` when the database logins connect, the store answers a `head` and the Temporal client is connected, and 503 `{"status": "not-ready"}` otherwise.
`routes.yaml` names no handler, so it holds no internal function name.

## Bodies

A batch submit and a batch control answer are NDJSON (`application/x-ndjson`), every other route takes and answers JSON, and an upload takes raw bytes.
An HTTP body is never a CloudEvent.
Each model of `routes.yaml` is a schema under [schemas/](schemas/), named as the route names it.

A batch submit sends one `batch-header` line, then one `batch-entry` line per job.
It is answered with one `entry-answer` line per entry in request order, then one `summary-line`, or an `error-line` last when the call stops after it began answering.
Every entry answered before an `error-line` is durable, and a resend of the whole call is safe.
The server answers each chunk of entries before it reads the next, so a client reads the answer lines while it sends.
A client that sends the whole body first is stopped by the answer write timeout, with every answered entry durable.

The batch key is required, and no key is ever generated.
The key of a job is its entry's `submission_key`, else `<batch key>/<index>`.
The batch id is `dsy_keys.batch_id(tenant, batch_key)` and the job id `dsy_keys.job_id(tenant, key)`.
An entry whose `priority_class` or `job_class` is absent takes the header's, and the header's defaults are `standard` and `short`.
A resent entry whose key exists answers `duplicate` with the existing row's status when its [fingerprint](#fingerprint) is the same, and `rejected` with `KEY_CONFLICT` otherwise, and changes nothing.
An `entry-answer` leaves out `index` and `job_id` only when its line did not parse far enough to name them.

A batch control call answers one `control-answer` or `entry-error` line per job of the batch, then one `summary-line`, or an `error-line` last when it stops.
A single control call answers one `control-answer`, whose `outcome` is `applied` when the row reached the target, `requested` when the request waits for the workflow or admission, and `noop` when nothing changed.
A refused control call answers an error body instead.

Every error answer is the body `error` (`{code, message, trace_id}`), with the HTTP status of its code in `reasons.yaml`.

### Limits

These are estimates that the characterization epic (#16) replaces.

| Limit | Value |
| --- | --- |
| entries per submit call | 100,000, and the next entry line stops the call with `TOO_MANY_ENTRIES` |
| entry line | 2,048 bytes, else the entry answers `ENTRY_TOO_LARGE` |
| header line | 1,052,672 bytes, the 1 MiB `max_document_bytes` of the template plus 4 KiB, else the call answers `HEADER_TOO_LARGE` |
| submit calls in flight | 2 per tenant and 4 per process, else `TOO_MANY_CALLS` |
| requests in flight | 16 per process, else `TOO_MANY_CALLS` |
| idle read and answer write | 60 s each, else `IDLE_TIMEOUT`, and no limit on the whole call |
| entries per chunk | 1,000 |
| jobs per page of a batch read | 1 to 1,000 |

## Reason codes

[reasons.yaml](reasons.yaml), with schema [reasons.schema.json](schemas/reasons.schema.json), one row per code.

Each code has the scopes where it may be answered: `call` for a batch submit call, `entry` for one entry of it, `upload`, `control`, `read`, or `any` route.
`http` is the status of an error answer with that code, and null for a code that is carried only in a line: an `entry` code in its `entry-answer`, and `IDLE_TIMEOUT` in an `error-line`, because the answer has already begun.

| Where a code appears | The scopes it must have |
| --- | --- |
| `reason` of an `entry-answer` | `entry` |
| `code` of an `entry-error` | `control` or `any` |
| `error.code` of an `error-line` | `call` or `any` |
| `code` of an error answer | any, with an `http` status |
| `refusal` of a control cell or overlay rule | `control` |

`UNKNOWN_TENANT` is a rejection at the API edge only, and never a dead-letter reason.

## Control table

[control.yaml](control.yaml), with schema [control.schema.json](schemas/control.schema.json).

A control call opens one transaction per job, reads the row with `lock_job`, decides on the locked row and writes in the same transaction, so admission's claim either committed before the lock or waits and then skips the row.
A batch control call does the same for each job of the batch in turn.

The overlay rules decide first, from the row's `requested_action` when an action is outstanding: `noop` answers the outstanding `control_seq`, `refused` answers its code, and `table` hands the call to the cells, which request the action with the next sequence.
A cell is chosen by the row's status, whether the job has a workflow, the action and, for a resume, whether a patch was sent and whether it equals the pending one.
A job at `accepted` has no workflow, a job at `admitted` or `running` is treated as having one, and for any other status the API asks Temporal.
`request` calls `request_action`, `moves` are status moves in order from the cell's status, `pending_patch: set-or-clear` sets `pending_patch_ref` to the patch when one is sent and clears it otherwise, and `events` are written with the row in one transaction.
The API sends only `cancel`, `terminate` and `pause` to a workflow, and admission alone sends `resume`.

The id of every event of the control stage is `dsy_keys.cloudevent_id(job_id, "", "", <type>, control_seq)` through `dsy_events.build_event`, with `sequence` equal to the request's `control_seq`.
The `job.accepted` and `job.published` events of the dispatch stage take sequence 0.

## Fingerprint

The fingerprint of a job is the lower-case hex SHA-256 of the UTF-8 bytes of the canonical JSON of `{"job_class", "manifest_sha256", "parameters", "priority_class", "seed"}`.
Canonical JSON sorts keys at every depth, writes no whitespace and does not escape non-ASCII characters, and numbers are written as Python's `json` module writes them.
`dsy_dispatchapi.contract.fingerprint` computes it, and [vectors/fingerprint.json](vectors/fingerprint.json), with schema [fingerprint.schema.json](schemas/fingerprint.schema.json), holds its input, canonical and output vectors.

## Trace context

Each job gets its own `traceparent` with a fresh trace id, stored on the row and in its accepted event, and returned as `trace_id` in its answer line.
A call has one root span whose links name the jobs of its first chunk, and its trace id is the `trace_id` of its error answer or `error-line`.

## Consumers

| Consumer | Reads |
| --- | --- |
| #14 load CLI | every route, body, reason code and the fingerprint, as a pure client |
| #17 test ladder | submit, status, cancel, pause and resume, in its end-to-end cases |
| #15 failure scenarios | the submit, control and status routes, under kills and outages |
| #16 characterization | the limits, which it replaces with measured values |

## Loader

`contracts/api/check.sh <file> [--as NAME]` runs `python -m dsy_dispatchapi.contract --check <file> [--as NAME]`.
`NAME` is the name of a schema under [schemas/](schemas/).
Without `--as`, the name is the directory under `vectors/` that holds the file, or else the file's stem, so `routes.yaml` is checked as `routes` and `vectors/fingerprint.json` as `fingerprint`.
It exits 0 when valid, 1 with `reason: <code>: <detail>` on stderr when not, and 2 on usage.
The loader reads `reasons.yaml`, the status contract and the stage contract through the package data of `dsy_dispatchapi`.

The first failing check wins, in this order.

| Reason | Applies to | Fails when |
| --- | --- | --- |
| `schema-violation` | every schema | the file does not match its model, which includes a code listed twice, two routes with one method and path, a cell whose outcome and writes disagree, and an answer whose fields do not fit its outcome |
| `too-large` | `batch-header`, `batch-entry` | the line is above its limit |
| `unknown-reason` | `control`, `entry-answer`, `entry-error`, `error-line`, `error` | a code is not in `reasons.yaml` |
| `reason-scope` | as `unknown-reason` | a code is used where its scopes do not allow it, as the table of [Reason codes](#reason-codes) says |
| `transition-not-allowed` | `control` | a cell names a move that is not in the status contract, marks it row-only where the status contract does not or the other way round, or makes a row-only move for a job that may have a workflow |
| `event-not-of-stage` | `control` | a cell names an event that the control stage does not emit |
| `control-cell-missing` | `control` | a status, workflow case, action and patch case has no cell or two, or an outstanding action and an action has no overlay rule or two |
| `fingerprint-mismatch` | `fingerprint` | a vector's canonical JSON or output differs from the formula |

`vectors/<name>/{valid,invalid/<reason>}/` hold the vectors, two valid files per schema and at least one invalid file under each reason that applies to it, and `packages/dispatchapi/tests/test_loader.py` runs them inside `just ci`.
The `too-large` case of `batch-header` is built by that test, because a line above 1 MiB is above what the repository's large-file hook allows.

## Changing it

The rule for changing this contract once pinned is in [Changing a contract](../../docs/contracts.md#changing-a-contract).
