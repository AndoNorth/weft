"""A built wheel works from a clean virtual environment, away from the repository."""

import subprocess
from pathlib import Path

from dsy_itest.wheels import clean_venv, workspace_closure

ROOT = Path(__file__).resolve().parents[3]

# What admission reads from its dependencies' package data: the tenancy profile and its intake
# queues, the event schemas its intake decodes with, and the start contract of the workflow.
PROBE = """
import sys
from pathlib import Path

import dsy_admission
from dsy_broker.tenancy import load
from dsy_broker.topology import intake_queues
from dsy_compat import read_event
from dsy_workflow.contract import naming
from dsy_workflow.models import ResumeSignal
from dsy_workflow.taskpath import QUEUE_PREFIX_MEMO

profile = load("ci")
assert profile.priority_classes == ["standard"]
assert {queue.rsplit(".", 1)[1] for queue in intake_queues(profile)} == {"standard"}
assert naming().workflow.type == "JobWorkflow"
assert QUEUE_PREFIX_MEMO == "dsy_pool_queue_prefix"
assert read_event(Path(sys.argv[1]).read_bytes()).type == "dev.dsy.job.accepted.v1"
"""
ACCEPTED = ROOT / "contracts/events/vectors/accepted/valid/accepted.json"


def test_wheel_in_a_clean_venv_imports_admission(tmp_path, tmp_path_factory):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    python = clean_venv(tmp_path_factory, workspace_closure("dsy-admission"))
    work = tmp_path / "work"
    work.mkdir()
    probe = subprocess.run(
        [python, "-I", "-c", PROBE, ACCEPTED], capture_output=True, text=True, cwd=work
    )
    assert probe.returncode == 0, probe.stderr
