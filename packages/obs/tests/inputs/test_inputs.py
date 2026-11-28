"""The state inputs exporter: its names held to the catalogue, and against a migrated database as
the `dsy_reader` group, a pass served on the Temporal runtime's Prometheus endpoint."""

import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
import yaml
from dsy_obs import metrics
from dsy_obs.inputs import Exporter, metric_name
from dsy_obs.inputs.__main__ import serve
from dsy_servicekit.testing import free_port
from dsy_stateops.inputs import load, parse

ROOT = Path(__file__).resolve().parents[4]
CATALOGUE = yaml.safe_load((ROOT / "contracts/instrumentation/metrics.yaml").read_text())["metrics"]
EXPORTED = [i for i in load().inputs if i.source.kind in ("sql", "sql_labelled", "invariants")]
READER = "t_state_reader"
UNREACHABLE = "postgresql://nobody@127.0.0.1:1/none"


def scrape(url: str) -> str:
    return urllib.request.urlopen(url, timeout=5).read().decode()


def series(text: str, name: str) -> dict[str, float]:
    """The samples of `name` keyed by their labels without the runtime's `service_name`, empty
    for an unlabelled one."""
    found = re.findall(rf"^{name}(\{{[^}}]*\}})? (\S+)$", text, re.MULTILINE)
    return {
        re.sub(r'[{,]?service_name="[^"]*",?', "", labels).strip("{},"): float(value)
        for labels, value in found
    }


@pytest.fixture(scope="module")
def served():
    """One runtime for the module, since its endpoint stays bound for the life of the process."""
    port = free_port()
    runtime = metrics.runtime(f"127.0.0.1:{port}", {})
    yield runtime.metric_meter, f"http://127.0.0.1:{port}/metrics"


@pytest.fixture
def reader(appdb):
    """The DSN of a login that is a member of `dsy_reader` only, as the module's login is."""
    with psycopg.connect(appdb, autocommit=True) as admin:
        admin.execute(f"drop role if exists {READER}")
        admin.execute(f"create role {READER} login password 'x' in role dsy_reader")
    parts = urlsplit(appdb)
    host = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit(parts._replace(netloc=f"{READER}:x@{host}"))


def test_the_names_are_the_catalogued_state_names():
    catalogued = {n for n in CATALOGUE if n.startswith("dsy_state_")}
    assert {metric_name(i) for i in EXPORTED} == catalogued


def test_the_store_inputs_are_not_exported():
    exporter = Exporter(metrics.runtime(f"127.0.0.1:{free_port()}", {}).metric_meter, "", load())
    assert {i.name for i in exporter.inputs} == {i.name for i in EXPORTED}
    assert not {"store_bytes", "store_capacity_share"} & {i.name for i in exporter.inputs}


def test_an_unreachable_database_counts_an_error_for_every_input(served):
    meter, _ = served
    exporter = Exporter(meter, UNREACHABLE, load())

    assert exporter.run_once() == 0
    assert exporter.errors == {i.name: 1 for i in EXPORTED}


def test_serve_marks_ready_after_a_pass_that_reached_the_database_and_clears_on_stop(tmp_path):
    ready, stop = tmp_path / "ready", threading.Event()
    seen: list[bool] = []

    class Pass:
        def __init__(self, reads: list[int]):
            self.reads = reads

        def run_once(self) -> int:
            seen.append(ready.exists())
            reads = self.reads.pop(0)
            if not self.reads:
                stop.set()
            return reads

    serve(Pass([0]), stop, ready, 0)
    assert seen == [False]
    assert not ready.exists()

    stop.clear()
    seen.clear()
    serve(Pass([0, 3, 0]), stop, ready, 0)
    assert seen == [False, False, True]
    assert not ready.exists()


@pytest.mark.integration
def test_every_input_is_served_as_its_gauge(reader, served):
    meter, url = served
    exporter = Exporter(meter, reader, load())

    assert exporter.run_once() == len(EXPORTED)
    assert not exporter.errors

    text = scrape(url)
    for item in EXPORTED:
        assert series(text, metric_name(item)), item.name
    assert series(text, "dsy_state_connections")[""] > 0
    assert series(text, "dsy_state_database_size_bytes")[""] > 0
    codes = CATALOGUE["dsy_state_artifact_failures"]["labels"]["code"]["values"]
    labels = "".join(series(text, "dsy_state_artifact_failures"))
    assert sorted(re.findall(r'code="([^"]+)"', labels)) == sorted(codes)


@pytest.mark.integration
def test_a_failing_query_keeps_the_last_value_and_counts_the_error(appdb, served):
    meter, url = served
    with psycopg.connect(appdb, autocommit=True) as admin:
        admin.execute("create table flip (n int)")
        admin.execute("insert into flip values (1)")
    inputs = parse(
        """
inputs:
  - name: flaky
    unit: rows
    source: {kind: sql, ref: select 10 / n from flip}
  - name: steady
    unit: rows
    source: {kind: sql, ref: select count(*) from flip}
"""
    )
    exporter = Exporter(meter, appdb, inputs)

    assert exporter.run_once() == 2
    assert series(scrape(url), "dsy_state_flaky") == {"": 10.0}

    with psycopg.connect(appdb, autocommit=True) as admin:
        admin.execute("update flip set n = 0")
        admin.execute("insert into flip values (1)")
    assert exporter.run_once() == 1

    text = scrape(url)
    assert series(text, "dsy_state_flaky") == {"": 10.0}
    assert series(text, "dsy_state_steady") == {"": 2.0}
    assert exporter.errors == {"flaky": 1}


@pytest.mark.integration
def test_the_process_serves_the_inputs_and_stops_on_sigterm(reader, tmp_path):
    port, ready = free_port(), tmp_path / "ready"
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("OTEL_", "DSY_"))},
        "DSY_STATE_INPUTS_DSN": reader,
        "DSY_METRICS_ADDRESS": f"127.0.0.1:{port}",
        "DSY_READY_FILE": str(ready),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "dsy_obs.inputs"], env=env, stdout=subprocess.PIPE, text=True
    )
    try:
        deadline = time.monotonic() + 30
        while not ready.exists():
            assert process.poll() is None, process.stdout.read()
            assert time.monotonic() < deadline, "the exporter never became ready"
            time.sleep(0.2)
        assert series(scrape(f"http://127.0.0.1:{port}/metrics"), "dsy_state_connections")[""] > 0
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=15) == 0
    finally:
        process.kill()
        process.stdout.close()


@pytest.mark.seam
def test_the_process_without_a_dsn_exits_2(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OTEL_", "DSY_"))}
    command = [sys.executable, "-m", "dsy_obs.inputs"]
    run = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == 2
    assert "DSY_STATE_INPUTS_DSN" in run.stderr


def test_a_negative_value_is_skipped_logged_and_counted_without_stopping_the_pass(served, caplog):
    meter, url = served
    item = parse(
        """
inputs:
  - name: negative_probe
    unit: rows
    source: {kind: sql, ref: select 1}
"""
    ).inputs[0]
    exporter = Exporter(meter, UNREACHABLE, load())
    exporter._gauges[item.name] = meter.create_gauge_float("dsy_state_negative_probe", "probe")

    exporter._set(item, [("negative_probe", -1), ("negative_probe", 4)])

    assert series(scrape(url), "dsy_state_negative_probe") == {"": 4.0}
    assert exporter.errors == {"negative_probe": 1}
    assert "negative_probe" in caplog.text
