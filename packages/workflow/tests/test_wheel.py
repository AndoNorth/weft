"""A built wheel works from a clean virtual environment, away from the repository."""

import subprocess
from pathlib import Path

import pytest
from dsy_itest.wheels import clean_venv, workspace_closure

ROOT = Path(__file__).resolve().parents[3]

PROBE = """
import asyncio
from dsy_workflow.contract import exit_classes, failure_classes, naming, pools, registry_pools
from dsy_workflow.models import CONTRACT
from dsy_workflow.placement import PlacementRequest, StaticPlacer
from dsy_workflow.testing import placer_contract
from dsy_workflow.testing.control import FakeControl
from dsy_workflow.testing.pool import staged_outputs

assert naming().namespace == "dsy"
assert set(pools().pools) == registry_pools() == set(staged_outputs())
assert failure_classes()["operator_interrupt"].budget == "free"
assert "guest_memory_cap" in exit_classes()
for name in ("failures.yaml", "status.yaml"):
    assert (CONTRACT / name).read_text(), name
placer_contract(StaticPlacer())
request = PlacementRequest(task_type="compile", cpu_milli=1000, memory_mib=1024, run_timeout_s=600)
assert StaticPlacer().place(request).queue == "dsy-compile"
assert set(FakeControl().activities()) >= {"emit", "load_plan"}
"""


@pytest.fixture(scope="module")
def clean_python(tmp_path_factory) -> Path:
    return clean_venv(tmp_path_factory, workspace_closure("dsy-workflow"))


def test_wheel_closure_follows_the_lock():
    closure = workspace_closure("dsy-workflow")
    assert {"dsy-workflow", "dsy-artifactreaper", "dsy-temporal", "dsy-storecheck"} <= set(closure)
    assert "dsy-migrate" not in closure


def test_wheel_in_a_clean_venv_loads_both_contracts_from_package_data(clean_python, tmp_path):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    probe = subprocess.run(
        [clean_python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=tmp_path
    )
    assert probe.returncode == 0, probe.stderr


@pytest.mark.parametrize(
    ("contract", "relative"),
    [
        ("activity", "failure-classes.yaml"),
        ("activity", "vectors/task-input/valid/simulate.json"),
        ("temporal", "naming.yaml"),
        ("temporal", "pools.yaml"),
        ("temporal", "vectors/status-query/valid/running.json"),
    ],
)
def test_wheel_loader_checks_a_file_away_from_the_repository(
    clean_python, tmp_path, contract, relative
):
    name = relative.split("/")[1] if relative.startswith("vectors/") else None
    copy = tmp_path / Path(relative).name
    copy.write_text((ROOT / "contracts" / contract / relative).read_text())
    command = [clean_python, "-I", "-m", "dsy_workflow.contract", "--check", str(copy)]
    result = subprocess.run(
        command + (["--as", name] if name else []), capture_output=True, text=True, cwd=tmp_path
    )
    assert result.returncode == 0, result.stderr
