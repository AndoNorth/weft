"""A built wheel works from a clean virtual environment, away from the repository, with only its
declared dependencies installed."""

import subprocess
import tomllib
from pathlib import Path

import pytest
from dsy_itest.wheels import clean_venv, workspace_closure

ROOT = Path(__file__).resolve().parents[3]

# Every module of the package is imported, and the fake answers the client, so a module that imports
# an undeclared dependency fails here and not only in the workspace environment.
PROBE = """
import importlib
import pkgutil

import opentelemetry.exporter.otlp.proto.http
import opentelemetry.sdk
import pyroscope
import temporalio
import dsy_events
import dsy_obs
import dsy_servicekit
import yaml
from dsy_obs import query
from dsy_obs.targets import JOBS
from dsy_obs.testing import FakeObs

for module in pkgutil.walk_packages(dsy_obs.__path__, "dsy_obs."):
    if not module.name.endswith(".__main__"):
        importlib.import_module(module.name)
assert "rabbitmq-detailed" in JOBS
with FakeObs(vectors={"up": [{"metric": {"job": "kubelet"}, "value": [0, "1"]}]}) as fake:
    assert query.prom(fake.url, "up")[0]["value"] == [0, "1"]
"""


@pytest.fixture(scope="module")
def clean_python(tmp_path_factory) -> Path:
    return clean_venv(tmp_path_factory, workspace_closure("dsy-obs"))


def test_wheel_declares_the_dependency_set():
    project = tomllib.loads((ROOT / "packages/obs/pyproject.toml").read_text())["project"]
    assert sorted(project["dependencies"]) == [
        "dsy-events",
        "dsy-servicekit",
        "opentelemetry-exporter-otlp-proto-http",
        "opentelemetry-sdk",
        "pyroscope-io",
        "pyyaml",
        "temporalio",
    ]


def test_wheel_in_a_clean_venv_imports_every_module(clean_python, tmp_path):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    probe = subprocess.run(
        [clean_python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=tmp_path
    )
    assert probe.returncode == 0, probe.stderr
