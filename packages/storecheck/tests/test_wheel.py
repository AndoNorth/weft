"""A built wheel works from a clean virtual environment, away from the repository."""

import subprocess
from pathlib import Path

import pytest
from dsy_itest.wheels import clean_venv

ROOT = Path(__file__).resolve().parents[3]

PROBE = """
import json
import yaml
from dsy_storecheck.contract import check
from dsy_storecheck.models import CONTRACT, Lifecycle, Products, Roles

for name in ("roles.yaml", "lifecycle.yaml", "products.yaml"):
    check(yaml.safe_load((CONTRACT / name).read_text()))
for name in ("layout.yaml", "retention.yaml", "store.schema.json"):
    assert (CONTRACT / name).is_file(), name
assert json.loads((CONTRACT / "store.schema.json").read_text())["anyOf"]
"""


@pytest.fixture(scope="module")
def clean_python(tmp_path_factory) -> Path:
    return clean_venv(tmp_path_factory, ("dsy-storecheck",))


def test_a_wheel_in_a_clean_venv_loads_the_committed_contract(clean_python, tmp_path):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    probe = subprocess.run(
        [clean_python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=tmp_path
    )
    assert probe.returncode == 0, probe.stderr


def test_a_wheel_cli_reports_a_missing_option_as_usage(clean_python, tmp_path):
    result = subprocess.run(
        [clean_python, "-I", "-m", "dsy_storecheck", "run", "--mode", "base"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 2, result.stderr
    assert result.stderr.startswith("usage: dsy_storecheck run")
