"""A built wheel works from a clean virtual environment, away from the repository."""

import subprocess
from pathlib import Path

import pytest
from dsy_itest.wheels import clean_venv

ROOT = Path(__file__).resolve().parents[3]

PROBE = """
import dsy_artifactreaper.__main__, dsy_artifactreaper.schedule
import dsy_artifactreaper
from dsy_artifactreaper.reap import load_windows
import importlib.resources as resources
import yaml

contract = resources.files("dsy_artifactreaper") / "contract"
for name in ("layout.yaml", "failures.yaml"):
    assert yaml.safe_load((contract / name).read_text()), name
assert load_windows().checkpoint_keep >= 2
"""


@pytest.fixture(scope="module")
def clean_python(tmp_path_factory) -> Path:
    return clean_venv(
        tmp_path_factory,
        (
            "dsy-artifactreaper",
            "dsy-artifactclient",
            "dsy-artifactindex",
            "dsy-compat",
            "dsy-events",
            "dsy-itest",
            "dsy-keys",
            "dsy-servicekit",
            "dsy-storecheck",
            "dsy-temporal",
        ),
    )


def test_a_wheel_in_a_clean_venv_loads_its_contract_files_and_imports(clean_python, tmp_path):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    probe = subprocess.run(
        [clean_python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=tmp_path
    )
    assert probe.returncode == 0, probe.stderr
