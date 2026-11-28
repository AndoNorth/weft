"""A built wheel works from a clean virtual environment, away from the repository."""

import subprocess
from pathlib import Path

import pytest
from dsy_itest.wheels import clean_venv

ROOT = Path(__file__).resolve().parents[3]

PROBE = """
import json
from dsy_eventstore.models import CONTRACT, EventRow

for name in ['layout.yaml', 'retention.yaml', 'retention.schema.json', 'event-row/1.json']:
    assert (CONTRACT / name).is_file(), name
schema = json.loads((CONTRACT / 'event-row/1.json').read_text())
assert set(schema["properties"]) == set(EventRow.model_fields)

from importlib import metadata, resources

entry = metadata.entry_points(group='dsy.migrations', name='eventstore')
assert [e.value for e in entry] == ['dsy_eventstore.migrations']
shipped = {f.name for f in resources.files('dsy_eventstore.migrations').iterdir()}
shipped = {n for n in shipped if n.endswith('.sql')}
assert shipped == {'0200_event.sql', '0201_event_job_index.sql', 'R__event_policies.sql'}, shipped

"""


@pytest.fixture(scope="module")
def clean_python(tmp_path_factory) -> Path:
    return clean_venv(tmp_path_factory, ("dsy-eventstore", "dsy-events", "dsy-keys", "dsy-compat"))


def test_a_wheel_in_a_clean_venv_reads_its_contract_files_and_matches_its_model(
    clean_python, tmp_path
):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    probe = subprocess.run(
        [clean_python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=tmp_path
    )
    assert probe.returncode == 0, probe.stderr
