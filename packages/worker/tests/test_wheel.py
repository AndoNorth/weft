"""A built wheel works from a clean virtual environment, away from the repository, and each pool's
extra adds exactly that pool's library and binary."""

import subprocess
import tomllib
from pathlib import Path

import pytest
from dsy_itest.wheels import clean_venv, workspace_closure

ROOT = Path(__file__).resolve().parents[3]

PROBE = """
import dsy_worker.__main__, dsy_worker.probe, dsy_worker.runner, dsy_worker.service
from dsy_worker.activity import run_task
from dsy_worker.config import ENV, Config
from dsy_worker.pools import aggregate, compile, simulate

environ = {name: "/var/dsy/x" for name in ENV.values()} | {"DSY_SLOT_MEMORY_MIB": "384"}
assert Config.from_env("simulate", environ).queue == "dsy-simulate"
assert run_task.__temporal_activity_definition.name == "run_task"
"""

EXTRAS = {
    "compile": {"uv", "dsy-compile"},
    "simulate": {"dsy-runtime"},
    "aggregate": {"dsy-aggregate"},
}


def lock() -> dict[str, dict]:
    return {p["name"]: p for p in tomllib.loads((ROOT / "uv.lock").read_text())["package"]}


def run(*cmd, **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    assert result.returncode == 0, f"{cmd}: {result.stdout}{result.stderr}"
    return result


def test_wheel_extras_add_each_pool_its_own_library():
    worker = lock()["dsy-worker"]
    extras = worker["optional-dependencies"]
    assert {pool: {d["name"] for d in extras[pool]} for pool in extras} == EXTRAS
    core = {d["name"] for d in worker["dependencies"]}
    assert "dsy-workflow" in core and not core & {"uv", "dsy-aggregate"}


def test_wheel_in_a_clean_venv_imports_every_module(tmp_path, tmp_path_factory):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    python = clean_venv(tmp_path_factory, workspace_closure("dsy-worker", extras=True))
    work = tmp_path / "work"
    work.mkdir()
    probe = subprocess.run([python, "-I", "-c", PROBE], capture_output=True, text=True, cwd=work)
    assert probe.returncode == 0, probe.stderr


@pytest.mark.parametrize("pool", EXTRAS)
def test_wheel_export_of_each_pool_lists_its_extra_only(pool):
    exported = run(
        "uv",
        "export",
        "--frozen",
        "--no-hashes",
        "--package",
        "dsy-worker",
        "--extra",
        pool,
        cwd=ROOT,
    ).stdout
    lines = {line.split("==")[0] for line in exported.splitlines() if line[:1].isalpha()}
    lines |= {line.removeprefix("-e ./packages/") for line in exported.splitlines()}
    assert ("uv" in lines) == (pool == "compile")
    assert ("aggregate" in lines) == (pool == "aggregate")
    assert {"workflow", "compile", "runtime", "itest", "componentize-py", "psycopg"} <= lines
