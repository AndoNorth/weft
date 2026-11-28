"""Built wheels work from a clean virtual environment, and the runner finds an installed package."""

import subprocess
from pathlib import Path

import pytest
from dsy_itest.wheels import clean_venv

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).parent / "fixture_pkg"

PROBE = """
from dsy_migrate import discover
assert [m.name for m in discover()] == ["0001_fixture_item.sql", "0002_fixture_note.sql"]
"""


@pytest.fixture(scope="module")
def clean_python(tmp_path_factory) -> Path:
    return clean_venv(tmp_path_factory, ("dsy-migrate", "dsy-itest"), [FIXTURE])


def test_wheel_finds_the_migrations_of_an_installed_package(clean_python, tmp_path):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    probe = subprocess.run(
        [clean_python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=tmp_path
    )
    assert probe.returncode == 0, probe.stderr


def test_wheel_cli_reports_an_unreachable_database(clean_python, tmp_path):
    dsn = "postgresql://postgres@127.0.0.1:1/none?connect_timeout=2"
    result = subprocess.run(
        [clean_python, "-I", "-m", "dsy_migrate", "check", "--dsn", dsn],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 3, result.stderr
