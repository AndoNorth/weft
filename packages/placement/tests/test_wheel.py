"""A built wheel works from a clean virtual environment, away from the repository."""

import subprocess
from pathlib import Path

from dsy_itest.wheels import clean_venv, workspace_closure

ROOT = Path(__file__).resolve().parents[3]

# What placement reads from its dependency's package data: the pool table and the pool queues that
# the static placer answers from, and the conformance test that a placer passes.
PROBE = """
import dsy_placement
from dsy_workflow.contract import naming, pools
from dsy_workflow.placement import StaticPlacer
from dsy_workflow.testing import placer_contract

assert set(naming().pools) == {"compile", "simulate", "aggregate"}
assert pools().estimate is False
placer_contract(StaticPlacer())
"""


def test_wheel_in_a_clean_venv_imports_placement(tmp_path, tmp_path_factory):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    python = clean_venv(tmp_path_factory, workspace_closure("dsy-placement"))
    work = tmp_path / "work"
    work.mkdir()
    probe = subprocess.run([python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=work)
    assert probe.returncode == 0, probe.stderr
