"""A built wheel works from a clean virtual environment, away from the repository."""

import subprocess
from pathlib import Path

import pytest
from dsy_itest.wheels import clean_venv

ROOT = Path(__file__).resolve().parents[3]

PROBE = """
import dsy_jobstate
import json
from dsy_jobstate.models import CONTRACT, JobRow
from dsy_jobstate.models import STATUSES
assert len(STATUSES) == 10
for name in ['status.yaml', 'limits.yaml', 'job-row/1.json']:
    assert (CONTRACT / name).is_file(), name
from importlib import metadata, resources
assert metadata.entry_points(group='dsy.migrations')['jobstate'].value == 'dsy_jobstate.migrations'
names = {f.name for f in resources.files('dsy_jobstate.migrations').iterdir()}
assert {'0100_accepted_job.sql', 'R__job_vocab.sql'} <= names, names
schema = json.loads((CONTRACT / 'job-row/1.json').read_text())
assert set(schema["properties"]) == set(JobRow.model_fields)

"""


@pytest.fixture(scope="module")
def clean_python(tmp_path_factory) -> Path:
    return clean_venv(tmp_path_factory, ("dsy-jobstate", "dsy-events", "dsy-keys"))


def test_a_wheel_in_a_clean_venv_reads_its_contract_files_and_matches_its_model(
    clean_python, tmp_path
):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    probe = subprocess.run(
        [clean_python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=tmp_path
    )
    assert probe.returncode == 0, probe.stderr
