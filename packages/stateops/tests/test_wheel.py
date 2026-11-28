"""A built wheel works from a clean virtual environment, away from the repository."""

import subprocess
from pathlib import Path

import pytest
from dsy_itest.wheels import clean_venv

ROOT = Path(__file__).resolve().parents[3]

PACKAGES = (
    "dsy-stateops",
    "dsy-jobstate",
    "dsy-events",
    "dsy-eventstore",
    "dsy-compat",
    "dsy-keys",
    "dsy-migrate",
    "dsy-storecheck",
    "dsy-itest",
)

PROBE = """
import dsy_stateops
from dsy_stateops.invariants import queries
from dsy_stateops.inputs import load
assert load().inputs
from importlib import resources
assert (resources.files('dsy_stateops.migrations') / 'R__roles.sql').is_file()
assert len(queries()) == 6, sorted(queries())
from dsy_stateops.windows import params
assert params()['failure_codes'] and params()['unreferenced_grace']
from datetime import UTC, datetime
from dsy_stateops.bench import EVENTS_PER_JOB, job_events, job_row
assert len(job_events(0, job_row(0), datetime.now(UTC))) == EVENTS_PER_JOB

"""


@pytest.fixture(scope="module")
def clean_python(tmp_path_factory) -> Path:
    return clean_venv(tmp_path_factory, PACKAGES)


def test_a_wheel_in_a_clean_venv_imports_and_lists_its_stubs(clean_python, tmp_path):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    probe = subprocess.run(
        [clean_python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=tmp_path
    )
    assert probe.returncode == 0, probe.stderr
