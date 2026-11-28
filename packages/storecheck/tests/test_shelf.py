"""`shelf` is a store with every contract bucket created."""

import pytest
from dsy_storecheck.contract import buckets
from dsy_storecheck.s3 import client

pytestmark = pytest.mark.integration


def test_shelf_holds_the_contract_buckets(shelf):
    listed = client(shelf.endpoint, shelf.credentials["admin"]).list_buckets()["Buckets"]
    assert {b["Name"] for b in listed} >= set(buckets())
