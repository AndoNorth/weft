"""The service answers the placer contract over HTTP, logs one line per answer without waiting for a
snapshot, refuses what is not a PlaceCall, serves the pool view, refuses a bad configuration with
exit 2 and marks itself ready once it listens."""

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest
from dsy_placement import service
from dsy_workflow.placement import PlacementRequest, ServicePlacer, StaticPlacer
from dsy_workflow.testing import placer_contract

SIMULATE = PlacementRequest(task_type="simulate", cpu_milli=250, memory_mib=512, run_timeout_s=900)
ENV = {"KUBERNETES_SERVICE_HOST": "10.96.0.1", "KUBERNETES_SERVICE_PORT": "443"}


def call(url: str, path: str, body: bytes | None = None, method: str = "POST") -> tuple[int, bytes]:
    request = urllib.request.Request(url + path, data=body, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_service_placer_contract_end_to_end(ci_api, running):
    served = running()
    placer_contract(ServicePlacer(served.url))
    assert ServicePlacer(served.url).place(SIMULATE) == StaticPlacer().place(SIMULATE)


def test_place_logs_one_line(ci_api, running, decisions, until):
    served = running()
    until(lambda: served.snapshotter.current()[0] is not None)
    placer = ServicePlacer(served.url)
    placer.place(SIMULATE, escalate=True)
    placer.place(SIMULATE.model_copy(update={"memory_mib": 600}))
    placer.place(SIMULATE.model_copy(update={"task_type": "no such\ntype"}))
    assert decisions() == [
        "placed type=simulate cpu_milli=250 memory_mib=512 escalate=true queue=dsy-simulate "
        "memory_class=512Mi escalated=false snapshot_age_s=0 ready_workers=1",
        'unschedulable type=simulate failure=insufficient_memory reason="600 MiB is above the 512 '
        'MiB simulate slot" snapshot_age_s=0 ready_workers=1',
        'unschedulable type="no such\\ntype" failure=no_matching_pool reason="no pool runs no '
        'such\\ntype tasks" snapshot_age_s=0 ready_workers=none',
    ]


def test_place_does_not_wait_for_snapshot(api, running, decisions, until):
    api.hold.clear()
    served = running()
    until(lambda: any(path.startswith("/api/v1/nodes?") for path, _ in api.requests))
    placer = ServicePlacer(served.url, timeout_s=1)
    for _ in range(100):
        started = time.monotonic()
        placer.place(SIMULATE)
        assert time.monotonic() - started < 1
    lines = decisions()
    assert len(lines) == 100
    assert all(line.endswith(" snapshot_age_s=none ready_workers=none") for line in lines)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"{}",
        json.dumps({"request": SIMULATE.model_dump(), "escalate": "yes"}).encode(),
        json.dumps({"request": SIMULATE.model_dump(), "priority": 1}).encode(),
        b"x" * (service.MAX_BODY + 1),
    ],
    ids=["empty", "not-json", "no-request", "escalate-not-bool", "unknown-field", "too-large"],
)
def test_bad_body_is_400(api, running, decisions, body):
    served = running()
    status, reply = call(served.url, "/place", body)
    assert status == 400
    assert reply.endswith(b"\n") and reply.count(b"\n") == 1
    assert decisions() == []


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/place"), ("POST", "/pools"), ("GET", "/"), ("POST", "/place/")]
)
def test_unknown_route_is_404(api, running, method, path):
    body = b"{}" if method == "POST" else None
    assert call(running().url, path, body, method)[0] == 404


def test_pools_view_shape(ci_api, running, until):
    ci_api.hold.clear()
    served = running()
    status, body = call(served.url, "/pools", method="GET")
    assert status == 200
    before = json.loads(body)
    assert before["snapshot"] is None and before["last_error"] is None
    assert before["pools"]["simulate"] == {
        "queue": "dsy-simulate",
        "slot": {
            "cpu_milli": 250,
            "memory_mib": 512,
            "schedule_to_start_s": 1800,
            "heartbeat_s": 60,
            "start_to_close_margin_s": 120,
        },
        "capacity": None,
    }

    ci_api.hold.set()
    until(lambda: served.snapshotter.current()[0] is not None)
    view = json.loads(call(served.url, "/pools", method="GET")[1])
    assert list(view["pools"]) == ["compile", "simulate", "aggregate"]
    assert view["pools"]["simulate"]["capacity"] == {
        "nodes": ["dsy-worker4"],
        "allocatable_cpu_milli": 400,
        "allocatable_memory_mib": 584,
        "requested_cpu_milli": 350,
        "requested_memory_mib": 562,
        "ready_workers": 1,
        "images": ["dsy-simulate-worker:tilt-0d5a8e3c7b2f1946"],
        "free_cpu_milli": 50,
        "free_memory_mib": 22,
    }
    assert set(view["snapshot"]) == {"taken_at", "age_s"} and 0 <= view["snapshot"]["age_s"] < 5
    assert view["last_error"] is None


@pytest.mark.parametrize(
    ("changes", "named"),
    [
        ({"DSY_PLACEMENT_LISTEN": "8080"}, "DSY_PLACEMENT_LISTEN"),
        ({"DSY_PLACEMENT_LISTEN": "0.0.0.0:http"}, "DSY_PLACEMENT_LISTEN"),
        ({"DSY_PLACEMENT_LISTEN": "0.0.0.0:65536"}, "DSY_PLACEMENT_LISTEN"),
        ({"DSY_SNAPSHOT_EVERY_S": "0"}, "DSY_SNAPSHOT_EVERY_S"),
        ({"DSY_SNAPSHOT_EVERY_S": "-5"}, "DSY_SNAPSHOT_EVERY_S"),
        ({"DSY_SNAPSHOT_EVERY_S": "nan"}, "DSY_SNAPSHOT_EVERY_S"),
        ({"DSY_SNAPSHOT_EVERY_S": "soon"}, "DSY_SNAPSHOT_EVERY_S"),
        ({"KUBERNETES_SERVICE_HOST": ""}, "KUBERNETES_SERVICE_HOST"),
        ({"KUBERNETES_SERVICE_PORT": "https"}, "KUBERNETES_SERVICE_PORT"),
    ],
)
def test_config_refused_exits_2(changes, named):
    with pytest.raises(service.BadEnv, match=named):
        service.Config.from_env(ENV | changes)


@pytest.mark.seam
def test_config_refused_exits_2_from_the_command():
    result = subprocess.run(
        [sys.executable, "-m", "dsy_placement"],
        env=os.environ | ENV | {"DSY_SNAPSHOT_EVERY_S": "soon"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "dsy_placement: DSY_SNAPSHOT_EVERY_S is 'soon', not a positive number\n"


def test_config_defaults():
    config = service.Config.from_env(ENV)
    assert config == service.Config(
        listen=("0.0.0.0", 8080),
        snapshot_every_s=30.0,
        ready_file=None,
        api_url="https://10.96.0.1:443",
    )
    ipv6 = service.Config.from_env(ENV | {"KUBERNETES_SERVICE_HOST": "fd00::1"})
    assert ipv6.api_url == "https://[fd00::1]:443"


@pytest.mark.seam
def test_ready_after_listen(ci_api, spawn, tmp_path, until):
    # A ready file left by a killed process is replaced, not taken as this one's.
    (tmp_path / "ready").write_text("stale")
    url, process, stdout = spawn()
    # Ready means listening: the first request after the file appears is answered.
    assert call(url, "/pools", method="GET")[0] == 200
    until(lambda: "snapshot first_read=true" in stdout.read_text())
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=10) == 0
    assert not (tmp_path / "ready").exists()
    lines = [json.loads(line)["msg"] for line in stdout.read_text().splitlines()]
    assert lines == [
        f"listening address={url} snapshot_every_s=30.0",
        "snapshot first_read=true ready_workers=compile:1,simulate:1,aggregate:1",
    ]


def test_ready_file_is_cleared_when_the_stop_lands_right_after_it_is_set(
    api, account, tmp_path, monkeypatch
):
    class Interrupted(service.ReadyFile):
        def set(self):
            super().set()
            raise SystemExit(0)

    monkeypatch.setattr(service, "ReadyFile", Interrupted)
    snapshotter = service.kube.Snapshotter(
        service.kube.Reader(api.url, str(account / "token"), str(account / "ca.crt")), 60
    )
    served = service.Service(("127.0.0.1", 0), snapshotter)
    with pytest.raises(SystemExit):
        served.serve(tmp_path / "ready")
    assert not (tmp_path / "ready").exists()
