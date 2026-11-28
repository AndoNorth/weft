"""The admission service: the cycle of one admission process over the intake queues of a tenancy
profile, the job rows and the workflows of one Temporal namespace.

`python -m dsy_admission.service` reads its configuration from the environment only, the names of
ENV and the optional ones beside it, serves the admission metrics on the Prometheus endpoint of
DSY_METRICS_ADDRESS, and drains on SIGTERM or SIGINT: it stops pulling, gives the cycle in progress
DRAIN_S to finish its grants, releases every message it still holds, closes its connections and
returns. When READY_ENV names a file, the service creates it once its cycle runs and removes it when
it starts to drain, so a readiness probe can test for it. A file left by a killed process is
removed before anything else.

The Temporal client connects lazily, so an outage of Temporal at start-up reaches the breaker of
the cycle like any other.
"""

import asyncio
import logging
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dsy_broker.client import Credentials, Delivery, connect
from dsy_broker.models import BrokerUnavailable, TenancyProfile
from dsy_obs import logs
from dsy_obs.metrics import export_registry
from dsy_obs.metrics import runtime as metrics_runtime
from dsy_servicekit import pg
from dsy_servicekit.config import ConfigError, require
from dsy_servicekit.lifecycle import ReadyFile, stopping
from dsy_temporal.client import connect as connect_temporal
from dsy_workflow.contract import naming
from dsy_workflow.models import QUEUE
from temporalio.client import Client
from temporalio.runtime import Runtime

from .. import start as starting
from ..breaker import dependency_of
from ..intake import Intake, Other, Start, Work, temporal_probe
from ..policy import Caps, Resume, Snapshot
from ..resume import Resumes, pending
from ..scan import Scanner, readmit
from .metrics import BUCKETS, Metrics

log = logging.getLogger(__name__)

ENV = {
    "temporal_address": "DSY_TEMPORAL_ADDRESS",
    "namespace": "DSY_TEMPORAL_NAMESPACE",
    # A login in dsy_admission.
    "dsn": "DSY_ADMISSION_DSN",
    "broker_address": "DSY_BROKER_ADDRESS",
    # The password of the broker user `admission`.
    "broker_password": "DSY_BROKER_PASSWORD",
    "profile": "DSY_TENANCY_PROFILE",
    "metrics_address": "DSY_METRICS_ADDRESS",
}
# Optional: the file that marks the service ready.
READY_ENV = "DSY_READY_FILE"
# Optional: a global cap below the profile's, which can only lower it.
GLOBAL_CAP_ENV = "DSY_ADMISSION_GLOBAL_CAP"
# Optional: put in front of every pool queue of the jobs it starts, so a run on fake pools keeps its
# tasks off the deployed pool workers.
PREFIX_ENV = "DSY_POOL_QUEUE_PREFIX"
BROKER_USER = "admission"
# How long the cycle in progress has to finish after a stop, which a start's RPC timeout meets, so
# the release and the close still fit the pod's grace period.
DRAIN_S = 15.0
# The longest a database connect waits. The breaker probes again after its backoff, so a short bound
# only makes an outage show sooner.
CONNECT_TIMEOUT_S = 2
# The scans of the rows that no message admits run on every this many cycles, the first included.
SCAN_EVERY = 10


@dataclass(frozen=True)
class Config:
    temporal_address: str
    namespace: str
    # The DSN and the broker password are secrets, so a printed configuration leaves them out.
    dsn: str = field(repr=False)
    broker_address: str
    broker_password: str = field(repr=False)
    profile: str
    metrics_address: str
    global_cap: int | None = None
    prefix: str = ""

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "Config":
        """The configuration of `environ`, or ConfigError naming every variable that is unset or
        empty, a global cap that is not a positive number, or a prefix that puts a pool queue
        outside the queue names of the activity contract."""
        required = require(environ, ENV)
        cap = environ.get(GLOBAL_CAP_ENV) or None
        if cap is not None and not (cap.isdecimal() and int(cap) > 0):
            raise ConfigError(f"{GLOBAL_CAP_ENV} is {cap!r}, not a positive number")
        prefix = environ.get(PREFIX_ENV, "")
        for queue in naming().pools.values():
            if not re.fullmatch(QUEUE, prefix + queue):
                raise ConfigError(
                    f"{PREFIX_ENV} gives the queue {prefix + queue!r}, outside {QUEUE}"
                )
        return cls(
            **required,
            global_cap=int(cap) if cap else None,
            prefix=prefix,
        )


def prometheus(address: str) -> Runtime:
    return metrics_runtime(address, BUCKETS)


class _Holding:
    """A broker connection whose consumers keep every delivery they drain in `held`, so a drain
    that cuts a cycle short can release the deliveries it still holds."""

    def __init__(self, connection, held: list[Delivery]):
        self._connection = connection
        self._held = held

    def consumer(self, queue: str) -> "_HoldingConsumer":
        return _HoldingConsumer(self._connection.consumer(queue), self._held)

    def close(self) -> None:
        self._connection.close()


class _HoldingConsumer:
    def __init__(self, consumer, held: list[Delivery]):
        self._consumer = consumer
        self._held = held

    def drain(self, n: int, timeout_s: float) -> list[Delivery]:
        got = self._consumer.drain(n, timeout_s)
        self._held.extend(got)
        return got


class Jobs:
    """The job rows' part of each cycle: the snapshot, with the resumes and the re-admissions that
    wait, the grant of each of them, and the restart of the rows found stuck at `admitted`.

    It keeps its own database connection, opened again once an outage closed it, and counts into
    `counts`, the counters of the intake keyed by name and label values.
    """

    def __init__(
        self,
        connect_db: Callable[[], psycopg.Connection],
        client: Client,
        prefix: str,
        counts: Counter[tuple[str, ...]],
        metrics: Metrics,
    ):
        self.connect_db = connect_db
        self.client = client
        self.prefix = prefix
        self.counts = counts
        self.metrics = metrics
        self.scanner = Scanner()
        self.resumes = Resumes(client)
        self._recovered = False
        self._db: psycopg.Connection | None = None

    @property
    def work(self) -> Work:
        return Work(self.snapshot, self.grant)

    async def snapshot(self, cycle: int) -> tuple[Snapshot, list[Other]]:
        db = await self._database()
        # Read before the snapshot, so a granted resume whose row moves on between the two reads
        # is counted twice for this cycle rather than not at all.
        rows = await asyncio.to_thread(pending, db)
        if not self._recovered:
            await self.resumes.recover(rows)
            self._recovered = True
        waiting = self.resumes.observe(rows)
        await self.resumes.recheck()
        began = time.monotonic()
        read = await asyncio.to_thread(self.scanner.snapshot, db, (cycle - 1) % SCAN_EVERY == 0)
        self.metrics.observe("dsy_admission_snapshot_seconds", time.monotonic() - began)
        for done in await self.scanner.restart(db, self.client, read.stuck, self.prefix):
            self._restarted(done.outcome)
        slots = dict(self.resumes.slots())
        snapshot = read.counts(slots)
        live: Counter[str] = Counter()
        for (_, job_class), n in (*read.live.items(), *slots.items()):
            live[job_class] += n
        resumes = Counter(resume.priority_class for resume in waiting)
        self.metrics.rows(live, snapshot.open, read.paused, resumes)
        return snapshot, [*waiting, *read.readmissions]

    async def grant(self, item: Other) -> bool:
        """Carries out the grant of a resume or a re-admission, and returns whether it took a slot.

        An outage raises, for the breaker. Any other failure of a resume keeps its slot, which the
        recheck sends again, and of a re-admission leaves its row to the message-less scans.
        """
        try:
            if isinstance(item, Resume):
                if not await self.resumes.grant(item):
                    return False
                self.counts["dsy_admission_resumed_total", item.priority_class] += 1
                return True
            outcome = await readmit(await self._database(), self.client, item.job_id, self.prefix)
        except Exception as error:
            if dependency_of(error):
                raise
            log.warning("the grant of job %s failed: %r", item.job_id, error)
            if isinstance(item, Resume):
                return True
            self.counts["dsy_admission_start_failed_total",] += 1
            return False
        if outcome == "started":
            self.counts["dsy_admission_readmitted_total", "resumed-before-start"] += 1
            return True
        if outcome == "duplicate":
            self.counts["dsy_admission_duplicates_total",] += 1
            return True
        self.counts["dsy_admission_skipped_total", outcome] += 1
        return False

    def export(self) -> None:
        """Sends the counters gained since the last export."""
        self.counts["dsy_admission_skipped_total", "no-workflow"] = self.resumes.no_workflow
        self.metrics.count(self.counts)

    def close(self) -> None:
        db, self._db = self._db, None
        if db is not None:
            db.close()

    def _restarted(self, outcome: str) -> None:
        if outcome == "started":
            self.counts["dsy_admission_readmitted_total", "stuck-admitted"] += 1
        elif outcome == "duplicate":
            self.counts["dsy_admission_duplicates_total",] += 1
        elif outcome == "failed":
            self.counts["dsy_admission_start_failed_total",] += 1
        elif outcome != "left":
            self.counts["dsy_admission_skipped_total", outcome] += 1

    async def _database(self) -> psycopg.Connection:
        if self._db is None or self._db.closed:
            self._db = await asyncio.to_thread(self.connect_db)
        return self._db


def connect_database(dsn: str) -> psycopg.Connection:
    """An autocommit connection whose connect gives up after CONNECT_TIMEOUT_S, so an unreachable
    database reaches the database breaker as an outage instead of blocking the cycle."""
    return pg.connect(dsn, autocommit=True, connect_timeout=CONNECT_TIMEOUT_S)


def _timed(start: Start, metrics: Metrics) -> Start:
    """`start`, observing each started job's wait from its submission, with the job and its trace
    bound to every log line of the start."""

    async def timed(row, accepted):
        with logs.bind(job_id=row.job_id, traceparent=row.traceparent):
            log.info("claimed job %s, starting its workflow", row.job_id)
            outcome = await start(row, accepted)
        if outcome == "started":
            waited = (datetime.now(UTC) - row.created_at).total_seconds()
            metrics.observe("dsy_admission_wait_seconds", waited, priority_class=row.priority_class)
        return outcome

    return timed


async def serve(
    config: Config,
    profile: TenancyProfile,
    *,
    connect_broker: Callable[[], object] | None = None,
    start: Start | None = None,
    runtime: Runtime | None = None,
    stop: asyncio.Event | None = None,
    ready_file: Path | None = None,
) -> None:
    """Runs the cycle until `stop` is set or the process gets SIGTERM or SIGINT, then drains.

    `connect_broker` opens a broker connection and `start` starts a claimed job's workflow, the
    real ones of the configuration when they are not given. A fatal error of the cycle is raised.
    """
    ready = ReadyFile(ready_file)
    ready.arm()
    with nullcontext(stop) if stop else stopping() as stop:
        runtime = runtime or prometheus(config.metrics_address)
        client = await connect_temporal(
            config.temporal_address, config.namespace, runtime=runtime, lazy=True
        )
        connect_broker = connect_broker or (
            lambda: connect(config.broker_address, Credentials(BROKER_USER, config.broker_password))
        )
        start = start or (
            lambda row, accepted: starting.start(client, row, accepted, config.prefix)
        )
        caps = Caps.of(profile, config.global_cap)
        held: list[Delivery] = []

        def connect_db() -> psycopg.Connection:
            return connect_database(config.dsn)

        export_registry(runtime.metric_meter, "admission")
        metrics = Metrics(runtime.metric_meter, profile.priority_classes, caps)
        intake = Intake(
            profile,
            caps,
            connect_broker=lambda: _Holding(connect_broker(), held),
            connect_db=connect_db,
            start=_timed(start, metrics),
            probe_temporal=temporal_probe(client),
        )
        jobs = Jobs(connect_db, client, config.prefix, intake.counts, metrics)
        log.info(
            "polling %s in namespace %s, global cap %d%s",
            ", ".join(intake.queues),
            config.namespace,
            caps.global_,
            f", pool queues behind {config.prefix}" if config.prefix else "",
        )
        try:
            await _run(intake, jobs, metrics, held, stop, ready)
        finally:
            intake.close()
            jobs.close()


async def _run(
    intake: Intake,
    jobs: Jobs,
    metrics: Metrics,
    held: list[Delivery],
    stop: asyncio.Event,
    ready: ReadyFile,
) -> None:
    def export() -> None:
        jobs.export()
        metrics.gauge("dsy_admission_breaker_open", intake.breakers.gauge(), "dependency")

    stopped = asyncio.create_task(stop.wait())
    try:
        ready.set()
        while True:
            # No message is held between cycles, so only the cycle in progress can hold one.
            held.clear()
            cycle = asyncio.create_task(intake.cycle(jobs.work))
            await asyncio.wait([cycle, stopped], return_when=asyncio.FIRST_COMPLETED)
            if stop.is_set():
                break
            wait_s = cycle.result()
            export()
            await asyncio.wait([stopped], timeout=wait_s)
            if stop.is_set():
                break
    finally:
        ready.clear()
        stopped.cancel()
    log.info("draining for at most %s s", DRAIN_S)
    await asyncio.wait([cycle], timeout=DRAIN_S)
    if not cycle.done():
        log.warning("the cycle in progress did not finish, it is cut short")
        cycle.cancel()
    await asyncio.gather(cycle, return_exceptions=True)
    for delivery in held:
        try:
            await asyncio.to_thread(delivery.release)
        except (RuntimeError, BrokerUnavailable):
            # Settled already, or lost with its connection, which spends one delivery of it.
            pass
    export()
    log.info("drained")
