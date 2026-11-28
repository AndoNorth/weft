"""The pool worker service: one activity worker on the pool's queue, one task at a time, which
drains on SIGTERM.

The queue is unversioned and the worker passes no deployment config, so it serves the workflows of
every build. On SIGTERM or SIGINT it removes the ready file, stops polling and gives the task in
flight DRAIN to finish. A task still running then is cancelled by the SDK as a worker shutdown,
which the activity stops and fails as `worker_shutdown`. The ready file is created once the worker
polls, and one left by a killed process is removed before the service connects.

The children of a task get TMPDIR under the scratch root, which the activity empties when a task
starts, so a stopped child's temporary files never outlive the next task.
"""

import asyncio
import logging
import os
import tempfile
from contextlib import nullcontext
from datetime import timedelta

from dsy_artifactclient.client import ArtifactClient
from dsy_obs.metrics import export_registry
from dsy_servicekit.lifecycle import ReadyFile, stopping
from dsy_storecheck.s3 import load_credentials
from dsy_temporal.client import connect
from temporalio.worker import Worker

from .activity import run_task, serving
from .config import Config
from .metrics import Metrics, runtime_of
from .pools import Context

STUBBED = ()

log = logging.getLogger(__name__)

# How long a task in flight at a stop may run on before it is stopped. An estimate.
DRAIN = timedelta(seconds=30)
# The directory of the scratch root that is the TMPDIR of the worker and its children.
TMP = "tmp"


async def serve(config: Config, stop: asyncio.Event | None = None) -> None:
    """Serves `run_task` on the pool's queue until `stop` is set or the process gets SIGTERM or
    SIGINT, then drains. A namespace the server does not know fails before the ready file is
    created."""
    ready = ReadyFile(config.ready_file)
    ready.arm()
    tmp = config.scratch / TMP
    tmp.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = tempfile.tempdir = str(tmp)
    with nullcontext(stop) if stop else stopping() as stop:
        runtime = runtime_of(os.environ)
        export_registry(runtime.metric_meter, f"{config.pool}-worker")
        client = await connect(
            config.temporal_address, config.namespace, runtime=runtime, check_namespace=True
        )
        # The store role of each pool is named after the pool.
        credentials = load_credentials(config.store_credentials)[config.pool]
        context = Context(
            store=ArtifactClient(config.store_endpoint, credentials),
            scratch=config.scratch,
            slot_memory_mib=config.slot_memory_mib,
            mirror=config.mirror,
        )
        worker = Worker(
            client,
            task_queue=config.queue,
            activities=[run_task],
            max_concurrent_activities=1,
            graceful_shutdown_timeout=DRAIN,
        )
        with serving(context, tmp, Metrics(runtime.metric_meter, config.pool)):
            log.info(
                "polling %s in namespace %s for pool %s, unversioned",
                config.queue,
                config.namespace,
                config.pool,
            )
            await _run_until(worker, stop, ready)


async def _run_until(worker: Worker, stop: asyncio.Event, ready: ReadyFile) -> None:
    running = asyncio.create_task(worker.run())
    stopped = asyncio.create_task(stop.wait())
    try:
        ready.set()
        await asyncio.wait([running, stopped], return_when=asyncio.FIRST_COMPLETED)
    finally:
        ready.clear()
    stopped.cancel()
    log.info("draining for at most %s", DRAIN)
    await worker.shutdown()
    await running
    log.info("drained")
