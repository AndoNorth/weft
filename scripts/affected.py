"""Reads changed paths, one per line, and prints which package tests cover them.

Prints `itest` followed by the changed packages, then `unit` followed by those packages and every
workspace member that depends on one of them, directly or through others.
Documentation outside packages/, as scripts/ci-paths.sh classifies it, needs no tests.
Any other path can reach tests that no package owns, so the script prints `full <path>` and exits 1.
Usage: affected.py [workspace root], which defaults to this repository.
"""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

CI_PATHS = Path(__file__).resolve().parent / "ci-paths.sh"


def is_docs(path):
    run = subprocess.run([CI_PATHS], input=path + "\n", capture_output=True, text=True, check=True)
    return run.stdout.strip() == "docs"


def members(root):
    """Maps each member's directory under packages/ to the member directories it depends on."""
    projects = {}
    for pyproject in sorted((root / "packages").glob("*/pyproject.toml")):
        data = tomllib.loads(pyproject.read_text())
        requirements = data["project"].get("dependencies", [])
        deps = {re.match(r"[A-Za-z0-9._-]+", req).group() for req in requirements}
        projects[data["project"]["name"]] = (pyproject.parent.name, deps)
    return {
        folder: {projects[d][0] for d in deps if d in projects}
        for folder, deps in projects.values()
    }


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    graph = members(root)
    changed = set()
    for path in filter(None, sys.stdin.read().splitlines()):
        parts = path.split("/")
        if parts[0] == "packages" and len(parts) > 2 and parts[1] in graph:
            changed.add(parts[1])
        elif parts[0] == "packages" or not is_docs(path):
            print(f"full {path}")
            return 1
    unit = set(changed)
    while grown := {m for m, deps in graph.items() if m not in unit and deps & unit}:
        unit |= grown
    print(" ".join(["itest", *(f"packages/{m}" for m in sorted(changed))]))
    print(" ".join(["unit", *(f"packages/{m}" for m in sorted(unit))]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
