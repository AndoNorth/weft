# Broker contract

Owner epic: #7 (broker, RabbitMQ).
Version: 3, in [VERSION](VERSION).
The [Consumers](#consumers) section names who reads each part.

RabbitMQ is the intake buffer for submitted jobs and nothing else.
It holds each accepted event between the dispatch API and admission, keeps it durable across restarts, and gives an intake message that cannot be processed a dead-letter queue with a reason that says how to recover it.
The broker never owns job state: Temporal owns workflow lifecycle, and Postgres owns the job rows.
This directory pins the topology, the message shape, the memory of the broker, the publish outcomes, the settle calls, the rules of the client, the dead-letter reasons and the alert rules.
The schemas are generated from the models of `dsy_broker.models` and never edited by hand.
The tenants and priority classes that the intake queues are named after live in the [tenancy contract](../tenancy/README.md).
The exchanges, the queues, the dead-letter path and the client calls are drawn in [docs/architecture/19-broker-intake-and-dead-letter.drawio](../../docs/architecture/19-broker-intake-and-dead-letter.drawio).

## Topology

[topology.yaml](topology.yaml), with schema [topology.schema.json](topology.schema.json).

| Key | v1 value | Rule |
| --- | --- | --- |
| `vhost` | `/` | one vhost |
| `intake_exchange` | `dsy.intake`, direct, durable | publishing to the exchange answers `released` for a routing key with no queue, where a publish to a missing queue address would be a refused link |
| `intake_queue` | template `intake.<tenant>.<class>`, quorum, initial group size 1, bound to `dsy.intake` by its own name | one per tenant and priority class of the tenancy profile, and the tenant and class patterns of the event profile hold no dot, so a name maps to one pair |
| `intake_policy` | `dsy-intake` on `^intake\.[a-z0-9][a-z0-9-]*\.[a-z0-9][a-z0-9-]*$`, applied to quorum queues: `delivery_limit` 5, `max_length` 1,000 (estimate), `overflow` `reject-publish`, `dead_letter_exchange` `dsy.dlx`, `dead_letter_strategy` `at-least-once`, `delayed_retry_type` `failed` with `delayed_retry_min` 1,000 and `delayed_retry_max` 30,000 ms | at-least-once dead-lettering needs `reject-publish` on the source queue, and a full queue rejects the publish so the backlog of a large batch waits in Postgres. The delayed retry spaces the five counted retries of a message 1, 2, 3, 4 and 5 s apart, so a transient failure needs 15 s to dead-letter it, and type `failed` leaves `release()` immediate |
| `dead_letter_exchange` | `dsy.dlx`, fanout, durable | every dead letter of every intake queue goes through it |
| `dead_letter_queue` | `intake.dlq`, quorum, initial group size 1, bound to `dsy.dlx` | one queue for every tenant, class and reason, with no length bound |
| `dlq_policy` | `dsy-dlq` on `^intake\.dlq$`: `delivery_limit` -1, which turns the limit off, and no message TTL | a dead letter leaves only by `dlq replay` or `dlq purge`, and `dlq list` marks one older than `dsy_compat.window.DEAD_LETTER_RETENTION_DAYS` as `stale` |
| `addresses` | publish to `/exchanges/dsy.intake/<routing key>`, consume from `/queues/<queue>` | the AMQP 1.0 address format of RabbitMQ 4.x |
| `message` | one `data` section, `content_type` `application/cloudevents+json; charset=utf-8`, `durable` true, no application-properties, no message annotations on publish | the `dev.dsy.job.accepted.v1` event in structured mode, with no context attribute mapped to an AMQP property |
| `annotations` | `x-opt-dsy-reason`, `x-opt-dsy-detail` of at most 1,024 characters | set by `dead_letter` in the same settle |
| `users` | `dispatch`, `admission`, `operator` | the permissions below |
| `ports` | `amqp` 5672, `prometheus` 15692 | the queue counts come from the detailed endpoint of `rabbitmq_prometheus` |
| `memory` | `limit_mib` 320, `high_watermark_mib` 192 | the request and the limit of the broker container are both `limit_mib`, and `vm_memory_high_watermark.absolute` is `high_watermark_mib`, 0.6 of it, set absolute so it never depends on the memory the container detects. A broker that recovers four full intake queues and a full `intake.dlq` after a restart peaks at about 160 MiB, which raised the alarm at a 256 MiB limit, and the alarm blocks every publisher |

Only the queue type is a declare argument, and every other queue setting is a policy, so a setting changes without re-declaring a queue.
An intake queue is an `intake.<tenant>.<class>` queue, and `intake.dlq` is not one.
The trace context travels in the `traceparent` attribute of the event only.

### Users

Each permission is a RabbitMQ regular expression on vhost `/`, and the empty string grants nothing.
No user may configure, and the image's default `guest` user is not created.
Each password is generated into the state directory and never committed.

| User | Write | Read | Why |
| --- | --- | --- | --- |
| `dispatch` | `^dsy\.intake$` | nothing | publishes accepted events, and a defect in dispatch cannot consume |
| `admission` | nothing | the intake queue pattern | consumes, and re-admits a job from its row, never by a publish |
| `operator` | `^dsy\.intake$` | `^intake\.dlq$` and the intake queue pattern | replays dead letters, and reads the intake queues for the regression suite only |

## Publish outcomes

| AMQP result | `Outcome` or error | Meaning | What the publisher does |
| --- | --- | --- | --- |
| `accepted` | `ACCEPTED` | the message is on its queue | records the receipt |
| `rejected` | `REJECTED` | the queue is full (`reject-publish`) | leaves the row unpublished for the reconciler |
| `released` | `UNROUTABLE` | no queue for the routing key, so the tenancy profile of the publisher and the broker topology differ | leaves the row unpublished and logs a defect |
| link refused with `amqp:not-found` | `TopologyError` | the exchange is missing | stops, a defect and never retried |
| no outcome within `timeout_s` | `PublishTimeout` | a memory or disk alarm, or a stalled broker | leaves the row unpublished for the reconciler |
| connection lost before the outcome | `BrokerUnavailable` | unknown | leaves the row unpublished, so a republish may duplicate, which admission's claim absorbs |

There is no broker-side dedup: the unique key of the job row stops duplicates at submit, and admission's claim absorbs a duplicate publish.

## Settle calls

On an intake queue the client sends only these outcomes, so `released` and `rejected` cannot be sent.

| Call | AMQP outcome | Counts toward the limit | Use |
| --- | --- | --- | --- |
| `ack()` | `accepted` | no, the message is gone | the workflow started, or the row says the message needs nothing |
| `retry()` | `modified`, `delivery-failed=true`, `undeliverable-here=false` | yes, and on a `last` delivery the broker dead-letters with `delivery_limit` | a failure of this message that may pass on a redelivery, which comes after the delayed retry of `dsy-intake` |
| `dead_letter(reason, detail)` | `modified`, `delivery-failed=true`, `undeliverable-here=true`, the two annotations | dead-letters at once with broker reason `rejected` | a message that can never be processed, or a `last` delivery |
| `release()` | `modified`, `delivery-failed=false`, `undeliverable-here=false` | no, and the message goes back to the head of its queue at once | a dependency outage, a job class at its cap, the consumer's internal breaker open, or the consumer's drain on shutdown, and never a fault of the one message |

A delivery's `delivery_count` counts the failed deliveries before it, 0 on the first, and `last` is true when it equals `delivery_limit`, on the sixth delivery.
A consumer dead-letters a `last` delivery with `ADMISSION_FAILED` instead of retrying it, so every dead letter caused by the consumer carries an application reason.
After a `release()` the consumer stops pulling from that queue until the cause clears, so a message is released at most once per outage, cap wait, breaker opening or shutdown.
A delivery held unsettled when its connection is lost, whether the broker closes it, the client closes it or the broker restarts, counts as a failed delivery: it comes back with its count raised by one, and a `last` one dead-letters with `delivery_limit`.
A message settled back, counted or not, goes ahead of every message never delivered, in the order the messages were settled back.

## Client rules

The client of `dsy_broker.client` holds to these rules, which RabbitMQ 4.4.0 makes necessary.

- A receiver starts at credit 0 and gets credit only through `flow(n)` and `drain(n)`, and the client never uses prefetch.
- The client grants credit only after the broker has answered the attach, because credit sent on a link that a refused attach has already detached ends the whole session with `amqp:session:unattached-handle`.
  A missing queue then raises `TopologyError` and leaves the connection usable.
- A refused permission ends the whole session with `amqp:unauthorized-access`, not only the link, so every link of that session fails with it.
- A link error never closes the connection, so the client builds on a plain proton `Handler` and not on `MessagingHandler`, which closes the connection on any link error and adds its own flow controller.
- The client never reconnects by itself, and a lost connection raises `BrokerUnavailable` on every pending call.

## Dead-letter reasons

[reasons.yaml](reasons.yaml), with schema [reasons.schema.json](reasons.schema.json), one row per code.
The reason of a dead letter is `x-opt-dsy-reason` when present, and `x-last-death-reason` otherwise.

| Code | Source | On an intake queue | Event | Recovery | Operator action |
| --- | --- | --- | --- | --- | --- |
| `MALFORMED` | application | expected | `job.dead.lettered` with `dlq_reason: MALFORMED` when the body names a job | `never` | `show`, then `purge`, and end the named job through the control API |
| `UNSUPPORTED_VERSION` | application | expected | `job.dead.lettered` with `dlq_reason: UNSUPPORTED_VERSION` | `after-fix` | deploy a reader of that major inside the replay window of a previous major, then `replay` |
| `ADMISSION_FAILED` | application | expected | none | `replay` | find the cause from the detail token and the admission log of the job, fix it, then `replay` |
| `delivery_limit` | broker | expected, when a last delivery is lost to a crash, a restart or a dropped connection | none | `replay` | check why the consumer lost it, then `replay` |
| `rejected` | broker | not expected without `x-opt-dsy-reason`, a consumer defect | none | `after-fix` | fix the consumer, then `replay` |
| `maxlen` | broker | not expected, because intake queues reject publishes | none | `after-fix` | fix the topology, then `replay` |
| `expired` | broker | not expected, because intake queues have no TTL | none | `after-fix` | fix the topology, then `replay` |

`after-fix` means fix the cause, then replay, and `dlq replay` refuses a code whose recovery is `never` unless `--force`.
A dead-lettered job keeps its row at `accepted`, so a replay can admit it, and the dead-letter queue is the only record of a message that names no job.
`job.dead.lettered` 1.0 carries only `MALFORMED` and `UNSUPPORTED_VERSION`, so `ADMISSION_FAILED` has no event until the events contract adds the code.

`x-opt-dsy-detail` starts with a stable token and `: `, then free text, so recovery can group dead letters without parsing the text.

| Code | Detail token |
| --- | --- |
| `MALFORMED` | the `reason` of the raised `dsy_events` error, or `wrong-type` for a valid event that is not `job.accepted`, `unknown-tenant` or `unknown-class` for a pair outside the consumer's tenancy profile, and `queue-mismatch` when the `tenant` or `priorityclass` of the body differs from the queue |
| `UNSUPPORTED_VERSION` | the `reason` of the raised `dsy_events` error |
| `ADMISSION_FAILED` | `no-row` for a job with no row, or the error class otherwise |

## Metrics and alerts

The queue counts come from the detailed endpoint of `rabbitmq_prometheus` on port 15692, `/metrics/detailed`, from two families, each series labelled with `vhost` and `queue`.

| Family | Series |
| --- | --- |
| `queue_coarse_metrics` | `rabbitmq_detailed_queue_messages_ready`, `rabbitmq_detailed_queue_messages_unacked`, `rabbitmq_detailed_queue_messages` |
| `queue_consumer_count` | `rabbitmq_detailed_queue_consumers` |

The client counts `dsy_broker_publish_total{outcome}`, `dsy_broker_settle_total{call}` and `dsy_broker_dead_letter_total{reason}` in the registry of `dsy_events.metrics`, as [contracts/instrumentation/README.md](../instrumentation/README.md) pins them.

The observability epic installs these alert rules with the Prometheus it deploys.

| Alert | Expression, on the detailed endpoint and the client counters | Why |
| --- | --- | --- |
| `DsyDeadLetterQueueNotEmpty` | `rabbitmq_detailed_queue_messages_ready` of `intake.dlq` above 0 for 5 minutes | every dead letter needs a recovery decision |
| `DsyIntakeQueueStalled` | an intake queue with `rabbitmq_detailed_queue_messages_ready` above 0 and `rabbitmq_detailed_queue_consumers` at 0 for 10 minutes | nothing admits the jobs of that queue, and a full queue alone is not alerted, because the backlog of a large batch waits in Postgres by design |
| `DsyIntakePublishUnroutable` | `dsy_broker_publish_total{outcome="unroutable"}` rising for 10 minutes | the topology differs from the tenancy profile of the publisher, a defect, while `rejected` is designed back-pressure and is not alerted |

## Consumers

| Consumer | Reads |
| --- | --- |
| #8 admission | the intake queues, the settle calls, the reason table and its detail tokens, and the `admission` user |
| #24 dispatch and control API | the intake exchange, the publish outcomes and the `dispatch` user |
| #13 observability | the counters, the detailed endpoint and the alert rules |
| #15 failure scenarios | the reason table and the dead-letter queue, through the regression suite and the dead-letter tool |
| #17 test ladder | the dead-letter queue, which a passing run leaves empty |

## Loader

`contracts/broker/check.sh <file> [--as NAME]` runs `python -m dsy_broker.contract --check <file> [--as NAME]`, the loader of both this contract and the tenancy contract.
`NAME` is `topology` or `reasons`.
Without `--as`, the name is the directory under `vectors/` that holds the file, or else the file's stem, so `topology.yaml` is checked as `topology`.
It exits 0 when valid, 1 with `reason: <code>: <detail>` on stderr when not, and 2 on usage.
The loader reads the event profile and the `job.dead.lettered` schemas through the package data of `dsy_events`.

The first failing check wins, in this order, where `bad-name`, `dlq-ttl-set` and `bad-user` apply to `topology.yaml` and `duplicate-code`, `event-code-mismatch` and `unexpected-recovery` to `reasons.yaml`.

| Reason | Fails when |
| --- | --- |
| `schema-violation` | the file does not match its model, which includes an intake policy with a TTL, a figure of `max_length` not marked as an estimate, an application code not in upper case, and a broker code that RabbitMQ never sets or that carries an event |
| `bad-name` | a template, exchange, queue or policy name breaks the topology rules: a name that is not dotted lower case or is above 255 bytes, a template other than `intake.<tenant>.<class>`, an intake policy that misses an intake queue or matches `intake.dlq`, a dead-letter policy that misses `intake.dlq` or matches an intake queue, a dead-letter queue that could be an intake queue, or an intake policy that dead-letters to another exchange |
| `dlq-ttl-set` | the dead-letter policy carries a message TTL |
| `duplicate-code` | `reasons.yaml` lists a code twice |
| `event-code-mismatch` | an application row whose event is `job.dead.lettered` names a code outside the `dlq_reason` enum of the newest schema of that event, or a value of that enum has no such row |
| `unexpected-recovery` | a row not expected on an intake queue has the recovery `replay`, or an expected row has none |
| `bad-user` | a user may configure, or `dispatch` may read, or `admission` may write, or a permission is not a regular expression |

`vectors/<name>/{valid,invalid/<reason>}/` hold the vectors, each the pinned file with one change, and `packages/broker/tests/test_loader.py` runs them inside `just ci`.

## Changing it

The rule for changing this contract once pinned is in [Changing a contract](../../docs/contracts.md#changing-a-contract).
A value PR is the one exception: it changes only `max_length`, the one number marked `estimate: true`, touches only `topology.yaml`, runs `check.sh` and lists the consumers, with no version bump.
A definitions import adds and updates but never deletes, so removing a tenant or a priority class from a running broker is out of scope.
