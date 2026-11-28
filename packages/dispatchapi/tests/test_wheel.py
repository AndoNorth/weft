"""A built wheel works from a clean virtual environment, away from the repository."""

import subprocess
from pathlib import Path

import pytest
from dsy_itest.wheels import clean_venv, workspace_closure

ROOT = Path(__file__).resolve().parents[3]

# The API contract and the contracts it is checked against come from package data, the tenancy
# profile from the broker's, and the stub of Temporal runs with no repository around it.
PROBE = """
from dsy_broker.tenancy import load
from dsy_dispatchapi.contract import control_table, reasons, routes
from dsy_dispatchapi.models import CONTRACT
from dsy_dispatchapi.testing import FakeGateway, gateway_contract

for name in ("routes.yaml", "reasons.yaml", "control.yaml", "status.yaml", "stages.yaml"):
    assert (CONTRACT / name).read_text(), name
assert "UNKNOWN_TENANT" in {r.code for r in reasons().reasons}
assert routes() and control_table()
profile = load("ci")
assert "acme" in profile.tenants
assert profile.priority_classes == ["standard"]
gateway = FakeGateway()
gateway.start("job")
gateway_contract(gateway, "job")
"""


@pytest.fixture(scope="module")
def clean_python(tmp_path_factory) -> Path:
    return clean_venv(tmp_path_factory, workspace_closure("dsy-dispatchapi"))


def test_wheel_in_a_clean_venv_loads_the_contracts_and_runs_the_stub(clean_python, tmp_path):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    probe = subprocess.run(
        [clean_python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=tmp_path
    )
    assert probe.returncode == 0, probe.stderr


@pytest.mark.parametrize("name", ["routes.yaml", "reasons.yaml", "control.yaml"])
def test_wheel_loader_checks_a_file_away_from_the_repository(clean_python, tmp_path, name):
    copy = tmp_path / name
    copy.write_text((ROOT / "contracts/api" / name).read_text())
    result = subprocess.run(
        [clean_python, "-I", "-m", "dsy_dispatchapi.contract", "--check", str(copy)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
