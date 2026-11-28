# Tenancy contract

Owner epic: #7 (broker, RabbitMQ).
Version: 4, in [VERSION](VERSION).
The [Consumers](#consumers) section names who reads each part.

This directory pins the tenants, the priority classes and the caps of each preset, in one file that the broker, admission and dispatch all read.
The broker names one intake queue after each tenant and priority class, admission reads the caps and the order of the classes, and dispatch refuses a tenant or a class outside the profile.
The format is this contract's, and the admission policy that applies the caps is admission's.
The schema is generated from the models of `dsy_broker.models` and never edited by hand.

## The file

[tenancy.yaml](tenancy.yaml), with schema [tenancy.schema.json](tenancy.schema.json), holds `profiles`, keyed by the preset names `ci`, `dev` and `soak`, and `tilt_profiles`.
A runtime reads a profile through package data with `dsy_broker.tenancy.load(profile)`, which returns the typed profile, and never by repository path.

| Field | Type | Rule | `ci` value |
| --- | --- | --- | --- |
| `priority_classes` | list of strings | ordered from first served to last, each matching the `priorityclass` pattern of the event profile, at least one, none twice | `[standard]` |
| `reserve_interval` | integer | at least 2: one admission in this many goes to the lowest waiting class | 5 (estimate) |
| `caps.open` | integer | at least `caps.global`, live and paused workflows across tenants | 2,000 (estimate) |
| `caps.global` | integer | at least 1, live workflows across tenants | 1,000 (estimate) |
| `caps.job_class` | map | keys equal `classes` of the same limits profile in `contracts/job/limits.yaml`, each matching the `jobclass` pattern, values at least 1 and at most `caps.global` | `short: 1000`, `long: 100` (estimates) |
| `tenants` | map | keys match the `tenant` pattern of the event profile, at least one | `acme`, `e2e` |
| `tenants.<t>.quota` | integer | at least 1 and at most `caps.global`, live workflows of the tenant | 1,000 (estimate) |
| `tilt_profiles` | map | top level, not per profile: every profile of `deploy/tilt/profiles.yaml` to a tenancy profile | `minimal: ci`, `ci: ci`, `dev: dev`, `full: dev`, `soak: soak` |

Every integer figure is written as `{value: N, estimate: true}`, so a value PR can tell which numbers it may change.
`dev` and `soak` use the `ci` values, as the limits profiles do.
The tenant `acme` is the tenant of every event vector, the tenant `e2e` is the tenant of the end-to-end acceptance run, and `standard` is the one priority class of the proof of concept.
A module learns the Tilt profile from `DSY_TILT_PROFILE` and passes the mapped tenancy profile to its service as `DSY_TENANCY_PROFILE`, so the broker, admission and dispatch always read one profile.

Two repository tests, in `packages/broker/tests/test_tenancy.py`, read by repository path and so stay out of the loader.
`test_tenancy_job_classes_match_limits` holds the keys of `caps.job_class` equal to the `classes` of each limits profile, read through `dsy_jobdoc.profile_files.load_profile`.
`test_tenancy_profiles_match_presets` holds the profile names equal to the presets of `deploy/presets/`, and the keys of `tilt_profiles` equal to the profiles of `deploy/tilt/profiles.yaml`.

## Consumers

| Consumer | Reads |
| --- | --- |
| #7 broker | the tenants and the priority classes, which name the intake queues |
| #8 admission | every field, and it never changes a figure |
| #24 dispatch and control API | the tenants and the priority classes, to refuse an unknown one at the edge |
| #16 characterization | the figures marked as estimates, which it measures and changes by value PRs |

## Loader

`contracts/tenancy/check.sh <file> [--as NAME]` runs `python -m dsy_broker.contract --check <file> [--as NAME]`, the loader of both this contract and the broker contract, where `NAME` is `tenancy`.
It exits 0 when valid, 1 with `reason: <code>: <detail>` on stderr when not, and 2 on usage.
The loader reads the event profile through the package data of `dsy_events`.

The first failing check wins, in this order.

| Reason | Fails when |
| --- | --- |
| `schema-violation` | the file does not match its model, which includes a `reserve_interval` below 2, a figure not marked as an estimate, a priority class listed twice and a profile with no tenant |
| `bad-tenant` | a tenant name breaks the `tenant` pattern of the event profile |
| `bad-class` | a priority class breaks the `priorityclass` pattern, or a job class the `jobclass` pattern |
| `cap-above-global` | a job class cap or a quota above `caps.global`, or `caps.global` above `caps.open` |
| `unknown-profile` | a profile name other than `ci`, `dev` and `soak`, or a Tilt profile mapped to a profile the file does not hold |

`vectors/tenancy/{valid,invalid/<reason>}/` hold the vectors, each the pinned file with one change, and `packages/broker/tests/test_loader.py` runs them inside `just ci`.

## Changing it

The rule for changing this contract once pinned is in [Changing a contract](../../docs/contracts.md#changing-a-contract).
A value PR is the one exception: it changes only numbers marked `estimate: true` (the caps, the quotas and `reserve_interval`), touches only `tenancy.yaml`, runs `check.sh` and lists the consumers, with no version bump.
A value PR never adds or removes a field, a tenant or a class, because a definitions import never deletes a queue and the messages of a removed queue would never be consumed.
