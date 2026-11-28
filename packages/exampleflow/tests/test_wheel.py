"""The wheel closure of the example installs into a clean virtual environment, away from the
repository, and the module is found there by its entry point."""

import subprocess
from pathlib import Path

import pytest
from dsy_itest.wheels import clean_venv, workspace_closure

pytestmark = pytest.mark.seam

ROOT = Path(__file__).resolve().parents[3]

PROBE = """
from importlib.metadata import entry_points

import dsy_exampleflow
from dsy_workflow import modules

[point] = [p for p in entry_points(group=modules.GROUP) if p.name == "exampleflow"]
assert point.load() is dsy_exampleflow.workers
assert "exampleflow" in [name for name, _ in modules.load()]
"""


@pytest.fixture(scope="module")
def clean_python(tmp_path_factory) -> Path:
    return clean_venv(tmp_path_factory, workspace_closure("dsy-exampleflow"))


def test_wheel_closure_follows_the_lock():
    closure = workspace_closure("dsy-exampleflow")
    assert {"dsy-exampleflow", "dsy-workflow", "dsy-temporal"} <= set(closure)


def test_wheel_in_a_clean_venv_finds_the_entry_point(clean_python, tmp_path):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    probe = subprocess.run(
        [clean_python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=tmp_path
    )
    assert probe.returncode == 0, probe.stderr
