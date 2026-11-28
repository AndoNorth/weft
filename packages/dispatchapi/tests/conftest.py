"""The fixtures that the API's test directories share.

Every container is held for one test module, so a module that holds two declares `pair` and no
session ever holds a third: Postgres comes from `appdb` of dsy_migrate with its `db` and `login`,
SeaweedFS from `shelf` of dsy_storecheck and the Temporal dev server from `temporal`. The database
logins are fresh members of the four group roles the service logs in through, the broker is
dsy_broker's own FakeBroker, and Temporal at T0 is FakeGateway.
"""

from pathlib import Path

import pytest
from dsy_broker.tenancy import load
from dsy_broker.testing import FakeBroker
from dsy_dispatchapi.testing import FakeGateway
from dsy_workflow.testing.server import dev_server

ROOT = Path(__file__).resolve().parents[3]
PROFILE = "ci"
# The group role of each service login: the submit sequence, control, index and link rows, and
# reads of event payloads.
GROUPS = {
    "dispatch": "dsy_dispatch",
    "control": "dsy_control",
    "artifacts": "dsy_artifacts",
    "reader": "dsy_reader",
}


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


@pytest.fixture
def logins(login) -> dict[str, str]:
    """The DSN of a fresh login in each group role of GROUPS, by its key."""
    return {key: login(group) for key, group in GROUPS.items()}


@pytest.fixture(scope="module")
def temporal(t1) -> str:
    """The address of a dev server with the namespace and search attributes of naming.yaml, one
    per test module."""
    with dev_server(t1, search_attributes=True) as address:
        yield address


@pytest.fixture(scope="session")
def tenancy():
    """The tenancy profile of the `ci` preset, as the service loads it."""
    return load(PROFILE)


@pytest.fixture
def broker() -> FakeBroker:
    return FakeBroker(PROFILE)


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()
