"""A built wheel works from a clean virtual environment, away from the repository."""

import subprocess
from pathlib import Path

import pytest
from dsy_itest.wheels import clean_venv

ROOT = Path(__file__).resolve().parents[3]

PROBE = """
import dsy_workloads.bundle, dsy_workloads.main
"""


@pytest.fixture(scope="module")
def clean_python(tmp_path_factory) -> Path:
    return clean_venv(
        tmp_path_factory,
        (
            "dsy-workloads",
            "dsy-kernel",
        ),
    )


def test_a_wheel_in_a_clean_venv_imports_every_module(clean_python, tmp_path):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    probe = subprocess.run(
        [clean_python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=tmp_path
    )
    assert probe.returncode == 0, probe.stderr
