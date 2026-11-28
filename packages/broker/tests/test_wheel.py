"""A built wheel works from a clean virtual environment, away from the repository."""

import subprocess
from pathlib import Path

import pytest
from dsy_itest.wheels import clean_venv, workspace_closure

ROOT = Path(__file__).resolve().parents[3]

PROBE = """
import proton
from dsy_broker.contract import reasons, tenancy, topology
from dsy_broker.models import CONTRACT
from dsy_broker.tenancy import load
from dsy_broker.testing import FakeBroker, broker_contract

assert proton.VERSION == (0, 40, 0)
assert topology().intake_policy.definition.delayed_retry_type == "failed"
assert "ADMISSION_FAILED" in {r.code for r in reasons().reasons}
assert set(tenancy().profiles) == {"ci", "dev", "soak"}
assert "acme" in load("ci").tenants
for name in ("topology.yaml", "reasons.yaml", "tenancy.yaml"):
    assert (CONTRACT / name).read_text(), name
broker = FakeBroker("ci")
broker_contract(lambda user: broker.connect())
"""


@pytest.fixture(scope="module")
def clean_python(tmp_path_factory) -> Path:
    return clean_venv(tmp_path_factory, workspace_closure("dsy-broker"))


def test_wheel_in_a_clean_venv_loads_both_contracts_and_runs_the_fake(clean_python, tmp_path):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    probe = subprocess.run(
        [clean_python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=tmp_path
    )
    assert probe.returncode == 0, probe.stderr


@pytest.mark.parametrize(
    "relative", ["broker/topology.yaml", "broker/reasons.yaml", "tenancy/tenancy.yaml"]
)
def test_wheel_loader_checks_a_file_away_from_the_repository(clean_python, tmp_path, relative):
    copy = tmp_path / Path(relative).name
    copy.write_text((ROOT / "contracts" / relative).read_text())
    result = subprocess.run(
        [clean_python, "-I", "-m", "dsy_broker.contract", "--check", str(copy)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
