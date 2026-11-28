"""A built wheel works from a clean virtual environment, away from the repository."""

import subprocess
from pathlib import Path

import pytest
from dsy_itest.wheels import clean_venv

ROOT = Path(__file__).resolve().parents[3]

PROBE = """
import json
from importlib import resources
from dsy_artifactindex.models import CONTRACT, ArtifactRow, ArtifactUse

for name in ['artifact-row/2.json', 'artifact-use/1.json']:
    assert (CONTRACT / name).is_file(), name
for name in ['0300_artifact_index.sql', '0301_artifact_use.sql', 'R__artifact_kinds.sql']:
    assert (resources.files('dsy_artifactindex.migrations') / name).is_file(), name
schema = json.loads((CONTRACT / 'artifact-row/2.json').read_text())
assert set(schema["properties"]) == set(ArtifactRow.model_fields)
schema = json.loads((CONTRACT / 'artifact-use/1.json').read_text())
assert set(schema["properties"]) == set(ArtifactUse.model_fields)

"""


@pytest.fixture(scope="module")
def clean_python(tmp_path_factory) -> Path:
    return clean_venv(tmp_path_factory, ("dsy-artifactindex", "dsy-events", "dsy-keys"))


def test_a_wheel_in_a_clean_venv_reads_its_contract_files_and_matches_its_model(
    clean_python, tmp_path
):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    probe = subprocess.run(
        [clean_python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=tmp_path
    )
    assert probe.returncode == 0, probe.stderr
