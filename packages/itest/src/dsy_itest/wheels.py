"""The workspace wheels, built once per pytest run and installed into clean virtual environments."""

import fcntl
import os
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def workspace_closure(package: str, extras: bool = False) -> list[str]:
    """The workspace packages that `package` needs, itself included, read from uv.lock.

    With `extras` the packages of every optional dependency group count as needed too.
    """
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text())
    packages = {p["name"]: p for p in lock["package"]}
    local = {name for name, p in packages.items() if "editable" in p.get("source", {})}
    seen, todo = set(), [package]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        found = packages[name]
        needs = [*found.get("dependencies", [])]
        if extras:
            for group in found.get("optional-dependencies", {}).values():
                needs += group
        todo += [d["name"] for d in needs if d["name"] in local]
    return sorted(seen)


def run(*cmd, **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    assert result.returncode == 0, f"{cmd}: {result.stdout}{result.stderr}"
    return result


def built_wheels(tmp_path_factory) -> Path:
    """The directory of every workspace wheel, built once under a file lock."""
    base = tmp_path_factory.getbasetemp()
    # Under xdist each worker has its own basetemp below the one the whole run shares.
    shared = base.parent if os.environ.get("PYTEST_XDIST_WORKER") else base
    wheels = shared / "workspace-wheels"
    with open(shared / "workspace-wheels.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not wheels.exists():
            partial = shared / "workspace-wheels.partial"
            run("uv", "build", "--wheel", "--all-packages", "-o", str(partial), cwd=REPO_ROOT)
            partial.rename(wheels)
    return wheels


def clean_venv(
    tmp_path_factory, packages: Iterable[str], extra_projects: Iterable[Path] = ()
) -> Path:
    """The python of a new venv holding the wheels of `packages` and of each extra project."""
    work = tmp_path_factory.mktemp("wheel")
    wheels = built_wheels(tmp_path_factory)
    chosen = [w for p in packages for w in wheels.glob(f"{p.replace('-', '_')}-*.whl")]
    assert len(chosen) == len(set(packages)), f"no wheel for some of {sorted(packages)}"
    for project in extra_projects:
        run("uv", "build", "--wheel", str(project), "-o", str(work / "extra"), cwd=work)
    venv = work / "venv"
    run("uv", "venv", "--python", sys.executable, str(venv))
    python = venv / "bin/python"
    run(
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        *map(str, [*chosen, *(work / "extra").glob("*.whl")]),
    )
    return python
