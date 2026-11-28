"""A built wheel of dsy_events works from a clean virtual environment, away from the repository."""

import json
import subprocess
from pathlib import Path

import pytest
from dsy_events.profile import CONTRACT_DIR
from dsy_itest.wheels import clean_venv

ROOT = CONTRACT_DIR.parents[1]
ACCEPTED = json.loads((CONTRACT_DIR / "vectors/accepted/valid/accepted.json").read_text())
CANONICAL = json.dumps(ACCEPTED, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

# Reads an event on stdin and writes its canonical bytes back, then moves the histogram metric.
# The reference models are built from the layout inside the wheel, so a working import proves it.
PROBE = """
import sys
from dsy_events import from_bytes, layout, to_bytes
from dsy_events.metrics import registry
from dsy_events.models import AttemptReference, ContentReference

data = sys.stdin.buffer.read()
assert to_bytes(from_bytes(data)) == data
assert registry.histograms["dsy_event_bytes"].count == 1
kinds = {*ContentReference.model_fields["kind"].annotation.__args__}
kinds |= {*AttemptReference.model_fields["kind"].annotation.__args__}
assert kinds == set(layout()["kinds"])
"""


@pytest.fixture(scope="module")
def clean_python(tmp_path_factory) -> Path:
    return clean_venv(tmp_path_factory, ("dsy-events", "dsy-keys"))


def test_a_wheel_in_a_clean_venv_reads_writes_and_counts(clean_python, tmp_path):
    """Runs isolated from a directory with no repository above it, so a path into the tree fails."""
    probe = subprocess.run(
        [clean_python, "-I", "-c", PROBE],
        input=CANONICAL.encode(),
        capture_output=True,
        cwd=tmp_path,
    )
    assert probe.returncode == 0, probe.stderr.decode()
