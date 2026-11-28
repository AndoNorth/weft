"""The workflow worker service: one build's workflow worker, its control activity worker and the
reaper's Schedule worker in one process, on a client of one namespace.

`python -m dsy_workflow.service` reads its configuration from the environment only, the names of
ENV and REAPER_ENV, serves the SDK's Prometheus metrics, which carry the workflow's own metrics,
on the address of DSY_METRICS_ADDRESS, and drains on SIGTERM or SIGINT: it stops polling, gives
the workflow, control and reaper tasks in flight DRAIN to finish and report, and returns.
When READY_ENV names a file, the service creates it once Temporal answers for its namespace and
its workers have started, and removes it when it starts to drain, so a readiness probe can test
for it. A file left by a killed process is removed before the service connects.
"""

import asyncio
import logging
import os
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path

from dsy_artifactreaper import schedule
from dsy_artifactreaper.schedule import RunPass
from dsy_jobstate import status_vocabulary
from dsy_obs import metrics
from dsy_servicekit.config import ConfigError, require
from dsy_servicekit.lifecycle import ReadyFile, stopping
from dsy_temporal.client import connect
from temporalio.common import MetricMeter
from temporalio.runtime import Runtime
from temporalio.worker import Worker

from ..activities.plan import limits
from ..contract import naming
from ..job import JOBS_TOTAL_HELP, JobWorkflow
from ..modules import Context, load
from ..placement import Placer, ServicePlacer, StaticPlacer
from ..worker import THREADS, control_worker, workflow_worker

log = logging.getLogger(__name__)

# How long the tasks in flight have to finish after a stop, below the pod's grace period.
DRAIN = schedule.DRAIN
# The workflow tasks run at once. A task takes tens of milliseconds of CPU, so on the pod's half
# core more of them at once only queue inside the process until they pass their timeout.
WORKFLOW_TASKS = 8
# The workflows kept in memory between their tasks, up to half a MiB each, so the cache fits in
# the pod's 256 MiB however many jobs are open. A workflow out of it replays its history on its
# next task.
CACHED_WORKFLOWS = 150

# The catalogue's buckets of the histograms the workflow creates on its own meter.
BUCKETS = {
    "dsy_workflow_history_events": [
        100,
        500,
        1000,
        2500,
        5000,
        10000,
        50000,
        100000,
        500000,
        1000000,
    ],
    "dsy_workflow_job_seconds": [60, 300, 900, 3600, 14400, 43200, 86400, 172800, 345600, 604800],
}

ENV = {
    "temporal_address": "DSY_TEMPORAL_ADDRESS",
    "namespace": "DSY_TEMPORAL_NAMESPACE",
    "build_id": naming().workflow.build_id_env,
    "metrics_address": "DSY_METRICS_ADDRESS",
    # A login in dsy_workflow, for emit.
    "workflow_dsn": "DSY_WORKFLOW_DSN",
    # A login in dsy_artifacts, for the control activities that write the index.
    "artifacts_dsn": "DSY_ARTIFACTS_DSN",
    "store_endpoint": "DSY_STORE_ENDPOINT",
    # Credentials files of dsy_storecheck.s3.load_credentials holding the role of each name.
    "workflow_credentials": "DSY_WORKFLOW_CREDENTIALS",
    "indexer_credentials": "DSY_INDEXER_CREDENTIALS",
    # Optional: the address of the placement service, StaticPlacer when unset.
    "placement_url": "DSY_PLACEMENT_URL",
}
OPTIONAL = {"placement_url"}
# Read by the reaper's own pass, with its login in dsy_reaper and the `reaper` store identity.
REAPER_ENV = (schedule.ENV_DSN, schedule.ENV_ENDPOINT, schedule.ENV_CREDENTIALS)
# Optional: the file that marks the service ready.
READY_ENV = "DSY_READY_FILE"


MissingEnv = ConfigError


@dataclass(frozen=True)
class Config:
    temporal_address: str
    namespace: str
    build_id: str
    metrics_address: str
    # The DSNs carry passwords, so a printed configuration leaves them out.
    workflow_dsn: str = field(repr=False)
    artifacts_dsn: str = field(repr=False)
    store_endpoint: str
    workflow_credentials: str
    indexer_credentials: str
    placement_url: str | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "Config":
        """The configuration of `environ`, or MissingEnv naming every variable that is unset or
        empty, the reaper's included and the optional ones left out, before anything connects."""
        required = {key: name for key, name in ENV.items() if key not in OPTIONAL}
        found = require(environ, {**required, **{name: name for name in REAPER_ENV}})
        return cls(
            **{key: found[key] for key in required},
            placement_url=environ.get(ENV["placement_url"]) or None,
        )

    def placer(self) -> Placer:
        return ServicePlacer(self.placement_url) if self.placement_url else StaticPlacer()


def real_control(config: Config) -> tuple[list[Callable], Callable]:
    """The control activities of the control queue, and `emit`, over the database logins and the
    store identities of the configuration."""
    from dsy_artifactclient.client import ArtifactClient
    from dsy_storecheck.s3 import load_credentials

    from ..activities import Committer, CompileCache, Emitter, IndexBuilder, PlanLoader

    def store(path: str, role: str) -> ArtifactClient:
        return ArtifactClient(config.store_endpoint, load_credentials(path)[role])

    reader = store(config.workflow_credentials, "workflow")
    indexer = store(config.indexer_credentials, "indexer")
    cache = CompileCache(config.artifacts_dsn, reader)
    committer = Committer(config.artifacts_dsn, reader)
    return [
        PlanLoader(reader).load_plan,
        cache.cache_lookup,
        cache.cache_record,
        cache.cache_invalidate,
        committer.commit,
        committer.index_checkpoint,
        IndexBuilder(config.artifacts_dsn, reader, indexer).build_index,
    ], Emitter(config.workflow_dsn).emit


def control_queue(build_id: str) -> str:
    return naming().control_queue.replace("<build id>", build_id)


def prometheus(address: str) -> Runtime:
    return metrics.runtime(address, BUCKETS)


def start_job_counters(meter: MetricMeter, namespace: str) -> None:
    """Creates the job-end counter at 0 for each job class and terminal status, since a counter
    with no increment is not exported and `increase` over the series of the first job to end is
    empty. The workflow's meter adds the namespace, task queue and workflow type to every series,
    so the zero series carry them too and are the series the first job then increments."""
    meter = meter.with_additional_attributes(
        {
            "namespace": namespace,
            "task_queue": naming().workflow.queue,
            "workflow_type": JobWorkflow.__name__,
        }
    )
    counter = meter.create_counter("dsy_workflow_jobs_total", JOBS_TOTAL_HELP)
    classes = {c for profile in limits().profiles.values() for c in profile.classes}
    for job_class in sorted(classes):
        for outcome in sorted(status_vocabulary().terminal):
            counter.add(0, {"job_class": job_class, "outcome": outcome})


async def serve(
    config: Config,
    control_activities: list[Callable],
    emit: Callable,
    run_pass: RunPass,
    stop: asyncio.Event | None = None,
    runtime: Runtime | None = None,
    ready_file: Path | None = None,
) -> None:
    """Runs the three workers until `stop` is set or the process gets SIGTERM or SIGINT, then
    drains them.

    The workflow reads its control queue from the environment's build id, so a `config.build_id`
    that differs from it, whose workflows would wait on a queue nobody polls, is refused. A
    namespace the server does not know fails before `ready_file` is created. A fatal error of any
    worker drains the others and is raised.
    """
    if (env_build := os.environ.get(naming().workflow.build_id_env)) != config.build_id:
        raise ValueError(f"build id {config.build_id} is not the environment's {env_build}")
    ready = ReadyFile(ready_file)
    ready.arm()
    with nullcontext(stop) if stop else stopping() as stop:
        runtime = runtime or prometheus(config.metrics_address)
        metrics.export_registry(runtime.metric_meter, "workflow")
        start_job_counters(runtime.metric_meter, config.namespace)
        client = await connect(
            config.temporal_address, config.namespace, runtime=runtime, check_namespace=True
        )
        with ThreadPoolExecutor(THREADS) as control, ThreadPoolExecutor(1) as reaper:
            workers = [
                workflow_worker(
                    client,
                    config.build_id,
                    config.placer(),
                    emit,
                    max_cached_workflows=CACHED_WORKFLOWS,
                    max_concurrent_workflow_tasks=WORKFLOW_TASKS,
                    graceful_shutdown_timeout=DRAIN,
                ),
                control_worker(
                    client,
                    config.build_id,
                    control_activities,
                    control,
                    graceful_shutdown_timeout=DRAIN,
                ),
                schedule.build_worker(client, run_pass, reaper),
            ]
            modules = build_modules(Context(client, config.build_id, DRAIN))
            log.info(
                "polling in namespace %s: %s as build %s of %s, %s and %s",
                config.namespace,
                naming().workflow.queue,
                config.build_id,
                naming().workflow.deployment,
                control_queue(config.build_id),
                schedule.TASK_QUEUE,
            )
            await _run_with_modules(modules, workers, stop, ready)


def build_modules(ctx: Context) -> list[tuple[str, Worker]]:
    """The workers of every module that loads and builds, named by their module. A module that
    raises while it builds its workers is logged and left out."""
    built = []
    for name, workers in load():
        try:
            built += [(name, worker) for worker in workers(ctx)]
        except Exception:
            log.exception("module %s is skipped: it failed to build its workers", name)
    return built


async def _supervise(name: str, worker: Worker) -> None:
    try:
        await worker.run()
    except Exception:
        log.exception("worker of module %s died, the service goes on without it", name)


async def _run_with_modules(
    modules: list[tuple[str, Worker]],
    workers: list[Worker],
    stop: asyncio.Event,
    ready: ReadyFile,
) -> None:
    """Runs the built-in `workers` under _run_until and each module worker under its own
    supervisor, and shuts the module workers down as soon as the built-in ones start to drain."""
    supervisors = [asyncio.create_task(_supervise(name, worker)) for name, worker in modules]
    builtin = asyncio.create_task(_run_until(workers, stop, ready))
    stopped = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait([builtin, stopped], return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopped.cancel()
        await asyncio.gather(*(worker.shutdown() for _, worker in modules), return_exceptions=True)
        await asyncio.gather(*supervisors)
    await builtin


async def _run_until(workers: list[Worker], stop: asyncio.Event, ready: ReadyFile) -> None:
    runs = [asyncio.create_task(worker.run()) for worker in workers]
    stopped = asyncio.create_task(stop.wait())
    try:
        ready.set()
        await asyncio.wait([*runs, stopped], return_when=asyncio.FIRST_COMPLETED)
    finally:
        ready.clear()
    stopped.cancel()
    log.info("draining for at most %s", DRAIN)
    await asyncio.gather(*(worker.shutdown() for worker in workers))
    await asyncio.gather(*runs)
    log.info("drained")
