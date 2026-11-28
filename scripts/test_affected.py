"""affected.py tests, run by `just ci`: changed paths pick the packages whose tests run."""

import subprocess
import sys
from pathlib import Path

import pytest

AFFECTED = Path(__file__).resolve().parent / "affected.py"


@pytest.fixture
def workspace(tmp_path):
    """Members a <- b <- c, where c depends on b and b on a, and an unrelated d."""
    deps = {"a": [], "b": ["a"], "c": ["b"], "d": []}
    for folder, needs in deps.items():
        requires = "".join(f', "dsy-{n}>=0"' for n in needs)
        (tmp_path / "packages" / folder).mkdir(parents=True)
        (tmp_path / "packages" / folder / "pyproject.toml").write_text(
            f'[project]\nname = "dsy-{folder}"\ndependencies = ["pyyaml"{requires}]\n'
        )
    return tmp_path


def affected(root, *paths):
    return subprocess.run(
        [sys.executable, AFFECTED, root], input="\n".join(paths), capture_output=True, text=True
    )


def test_a_change_runs_its_dependents_unit_tests(workspace):
    run = affected(workspace, "packages/a/src/dsy_a/core.py")
    assert run.returncode == 0, run.stderr
    assert run.stdout.splitlines() == [
        "itest packages/a",
        "unit packages/a packages/b packages/c",
    ]


def test_a_leaf_change_runs_only_its_own_tests(workspace):
    run = affected(workspace, "packages/c/tests/test_c.py", "packages/d/README.md")
    assert run.stdout.splitlines() == ["itest packages/c packages/d", "unit packages/c packages/d"]


def test_documentation_outside_packages_runs_no_tests(workspace):
    run = affected(workspace, "docs/dev-setup.md", "README.md")
    assert run.returncode == 0, run.stderr
    assert run.stdout.splitlines() == ["itest", "unit"]


@pytest.mark.parametrize(
    "path",
    [
        "scripts/ci.sh",
        "deploy/versions.yaml",
        "contracts/job/job.schema.json",
        "uv.lock",
        "pyproject.toml",
        "flake.nix",
        "packages/README.md",
        "packages/gone/src/dsy_gone/__init__.py",
    ],
)
def test_a_path_no_package_owns_names_the_full_run(workspace, path):
    run = affected(workspace, "packages/a/src/dsy_a/core.py", path)
    assert run.returncode == 1
    assert run.stdout == f"full {path}\n"
