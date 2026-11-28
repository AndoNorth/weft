"""The placement service: `POST /place` answers a `PlaceCall` with the policy's `PlaceResult`, and
`GET /pools` answers the pool view, each pool's queue and slot with its capacity in the last good
snapshot. Anything else is 404.

Each answer is one decision log line on stdout, with the age of the snapshot and the ready workers
of the task's pool, and a placement never waits for a snapshot read. The configuration comes from
the environment only, and the service reads the Kubernetes API with the pod's service account.
"""

import json
import logging
import os
import re
import signal
import time
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dsy_obs import metrics as obs_metrics
from dsy_obs.setup import setup
from dsy_servicekit.config import (
    ConfigError,
    exiting_on_config_error,
    host_port,
    positive,
    require,
)
from dsy_servicekit.lifecycle import ReadyFile
from dsy_workflow import contract, placement
from dsy_workflow.placement import PlaceCall, PlaceResult
from pydantic import ValidationError

from . import kube, policy
from .metrics import BUCKETS, Metrics

log = logging.getLogger(__name__)

ENV = {
    "listen": "DSY_PLACEMENT_LISTEN",
    "snapshot_every_s": "DSY_SNAPSHOT_EVERY_S",
    "ready_file": "DSY_READY_FILE",
    "metrics_address": "DSY_METRICS_ADDRESS",
    "api_host": "KUBERNETES_SERVICE_HOST",
    "api_port": "KUBERNETES_SERVICE_PORT",
}
LISTEN = "0.0.0.0:8080"
SNAPSHOT_EVERY_S = 30.0
METRICS_ADDRESS = "0.0.0.0:9464"
ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")
# A PlaceCall is a few hundred bytes, so a larger body is refused unread.
MAX_BODY = 64 * 1024
# A value that needs no quoting to stay one field of the decision log line.
PLAIN = re.compile(r"[\w.:/,-]+")


BadEnv = ConfigError


@dataclass(frozen=True)
class Config:
    listen: tuple[str, int]
    snapshot_every_s: float
    ready_file: Path | None
    api_url: str
    metrics_address: str = METRICS_ADDRESS

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "Config":
        """The configuration of `environ`, or BadEnv naming the first variable that is wrong."""
        listen = host_port(environ.get(ENV["listen"]) or LISTEN, ENV["listen"])
        every_s = positive(environ, ENV["snapshot_every_s"], SNAPSHOT_EVERY_S)
        api_host = require(environ, {"api_host": ENV["api_host"]})["api_host"]
        api_port = host_port(
            f"{api_host}:{environ.get(ENV['api_port']) or '443'}", ENV["api_port"]
        )[1]
        ready = environ.get(ENV["ready_file"])
        return cls(
            listen=listen,
            snapshot_every_s=every_s,
            ready_file=Path(ready) if ready else None,
            metrics_address=environ.get(ENV["metrics_address"]) or METRICS_ADDRESS,
            api_url=f"https://[{api_host}]:{api_port}"
            if ":" in api_host
            else f"https://{api_host}:{api_port}",
        )


def _field(value) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return str(value).lower()
    text = str(value)
    return text if PLAIN.fullmatch(text) else json.dumps(text)


def _line(verdict: str, **fields) -> str:
    return " ".join([verdict, *(f"{name}={_field(value)}" for name, value in fields.items())])


class Service:
    """The HTTP server over the policy and a snapshotter, bound and listening once constructed."""

    def __init__(
        self,
        listen: tuple[str, int],
        snapshotter: kube.Snapshotter,
        metrics: Metrics | None = None,
    ):
        self.metrics = metrics
        self.placer = policy.policy()
        self.snapshotter = snapshotter
        self.queues = contract.naming().pools
        self.slots = {name: row.model_dump() for name, row in contract.pools().pools.items()}
        self.task_pools = placement.task_pools()
        self.server = ThreadingHTTPServer(listen, _handler(self))

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def place(self, call: PlaceCall) -> PlaceResult:
        began = time.monotonic()
        answer = self.placer.place(call.request, call.escalate)
        seconds = time.monotonic() - began
        snapshot, age_s, _ = self.snapshotter.current()
        pool = self.task_pools.get(call.request.task_type)
        if self.metrics and pool:
            verdict = "placed" if answer.kind == "placement" else "unschedulable"
            self.metrics.decided(pool, verdict, call.escalate, seconds)
            self.metrics.snapshot_age_s(age_s)
        capacity = snapshot.pools.get(pool) if snapshot else None
        known = {
            "snapshot_age_s": None if age_s is None else round(age_s),
            "ready_workers": capacity.ready_workers if capacity else None,
        }
        request = call.request
        if answer.kind == "placement":
            line = _line(
                "placed",
                type=request.task_type,
                cpu_milli=request.cpu_milli,
                memory_mib=request.memory_mib,
                escalate=call.escalate,
                queue=answer.queue,
                memory_class=answer.memory_class,
                escalated=answer.escalated,
                **known,
            )
        else:
            line = _line(
                "unschedulable",
                type=request.task_type,
                failure=answer.failure,
                reason=answer.reason,
                **known,
            )
        log.info(line)
        return PlaceResult(answer)

    def view(self) -> dict:
        """Each task pool's queue, slot and capacity, and the snapshot's age and last error."""
        snapshot, age_s, error = self.snapshotter.current()
        pools = {}
        for name, queue in self.queues.items():
            capacity = snapshot.pools.get(name) if snapshot else None
            if capacity:
                capacity = capacity.model_dump() | {
                    "free_cpu_milli": capacity.free_cpu_milli,
                    "free_memory_mib": capacity.free_memory_mib,
                }
            pools[name] = {"queue": queue, "slot": self.slots.get(name), "capacity": capacity}
        return {
            "pools": pools,
            "snapshot": snapshot and {"taken_at": snapshot.taken_at.isoformat(), "age_s": age_s},
            "last_error": error,
        }

    def serve(self, ready_file: Path | None = None) -> None:
        """Serves until `stop()`, with `ready_file` present while it does."""
        ready = ReadyFile(ready_file)
        try:
            # Inside the try: SIGTERM raises SystemExit and may land right after the set.
            ready.set()
            self.server.serve_forever()
        finally:
            ready.clear()
            self.server.server_close()

    def stop(self) -> None:
        self.server.shutdown()


def _handler(service: Service) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _refuse(self, status: int, reason: str) -> None:
            self._send(status, " ".join(reason.split()).encode() + b"\n", "text/plain")

        def do_POST(self):
            if self.path != "/place":
                return self._refuse(404, f"no route POST {self.path}")
            length = self.headers.get("Content-Length", "0")
            if not length.isdigit() or int(length) > MAX_BODY:
                return self._refuse(400, f"Content-Length {length!r} is not up to {MAX_BODY}")
            try:
                call = PlaceCall.model_validate_json(self.rfile.read(int(length)))
            except ValidationError as error:
                return self._refuse(400, f"not a PlaceCall: {error}")
            self._send(200, service.place(call).model_dump_json().encode(), "application/json")

        def do_GET(self):
            if self.path != "/pools":
                return self._refuse(404, f"no route GET {self.path}")
            self._send(200, json.dumps(service.view()).encode(), "application/json")

        def log_message(self, *args):
            # The decision log is the record of each answer.
            pass

    return Handler


def main(environ: Mapping[str, str] = os.environ, account: Path = ACCOUNT) -> int:
    """Serves until SIGTERM or SIGINT, reading the API with the service account under `account`.
    Exit 2 when the configuration is refused."""
    setup("placement")
    with exiting_on_config_error("dsy_placement"):
        config = Config.from_env(environ)
    # A file left by a killed process must not claim a server that is not listening yet.
    ReadyFile(config.ready_file).arm()
    reader = kube.Reader(config.api_url, str(account / "token"), str(account / "ca.crt"))
    first = True

    def build(nodes: dict, pods: dict):
        nonlocal first
        snapshot = kube.pool_snapshot(nodes, pods)
        if first:
            first = False
            ready = ",".join(f"{name}:{p.ready_workers}" for name, p in snapshot.pools.items())
            log.info(_line("snapshot", first_read=True, ready_workers=ready))
        return snapshot

    snapshotter = kube.Snapshotter(reader, config.snapshot_every_s, build=build)
    runtime = obs_metrics.runtime(config.metrics_address, BUCKETS)
    obs_metrics.export_registry(runtime.metric_meter, "placement")
    service = Service(config.listen, snapshotter, Metrics(runtime.metric_meter))
    snapshotter.start()

    def stop(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info(_line("listening", address=service.url, snapshot_every_s=config.snapshot_every_s))
    service.serve(config.ready_file)
    return 0
