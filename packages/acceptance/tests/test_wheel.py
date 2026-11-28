"""A built wheel works from a clean virtual environment, away from the repository, with only its
declared dependencies installed."""

import subprocess
import tomllib
from pathlib import Path

import pytest
from dsy_itest.wheels import clean_venv, workspace_closure

ROOT = Path(__file__).resolve().parents[3]

# Every module of the package is imported, so a module that imports an undeclared dependency fails
# here and not only in the workspace environment, where the dev group installs every package.
PROBE = """
import importlib
import pkgutil

import psycopg
import temporalio
import dsy_acceptance
import dsy_broker
import dsy_clusterkit
import dsy_eventstore
import dsy_jobstate
import dsy_kernel
import dsy_keys
import dsy_obs
import dsy_storecheck
import dsy_temporal
import dsy_workflow
import dsy_workloads
from dsy_acceptance.report import count_line, ok

for module in pkgutil.walk_packages(dsy_acceptance.__path__, "dsy_acceptance."):
    if not module.name.endswith(".__main__"):
        importlib.import_module(module.name)
assert count_line("ci", [ok("api", "ready")], 1) == "smoke ci: 1 ok, 0 failed, 0 skipped, 1 s"
"""


@pytest.fixture(scope="module")
def clean_python(tmp_path_factory) -> Path:
    return clean_venv(tmp_path_factory, workspace_closure("dsy-acceptance"))


def test_wheel_declares_the_dependency_set():
    project = tomllib.loads((ROOT / "packages/acceptance/pyproject.toml").read_text())["project"]
    assert sorted(project["dependencies"]) == [
        "dsy-broker",
        "dsy-clusterkit",
        "dsy-eventstore",
        "dsy-jobstate",
        "dsy-kernel",
        "dsy-keys",
        "dsy-obs",
        "dsy-storecheck",
        "dsy-temporal",
        "dsy-workflow",
        "dsy-workloads",
        "psycopg[binary]",
        "temporalio",
    ]


def test_wheel_in_a_clean_venv_imports_every_module(clean_python, tmp_path):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    probe = subprocess.run(
        [clean_python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=tmp_path
    )
    assert probe.returncode == 0, probe.stderr
