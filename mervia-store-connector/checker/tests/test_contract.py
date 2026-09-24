from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from mervia_check import contract

CHECKER = Path(__file__).resolve().parent.parent
REPO_CONTRACT = CHECKER.parent / "contract"
BUNDLED = CHECKER / "src" / "mervia_check" / "contract"


def test_openapi_parses_and_is_31():
    doc = contract.openapi()
    assert doc["openapi"].startswith("3.1")
    assert {"/store", "/products", "/orders", "/articles", "/products/{id}/content"} <= set(doc["paths"])


@pytest.mark.parametrize("name", contract.schema_files())
def test_standalone_schemas_are_valid(name):
    Draft202012Validator.check_schema(contract.schema_file(name))


def test_the_order_object_is_defined_once():
    """GET /orders items and the order webhook's order both resolve to schemas/order.schema.json."""
    order_id = contract.schema_file("order.schema.json")["$id"]
    assert contract.openapi()["components"]["schemas"]["Order"]["$ref"] == order_id
    assert contract.schema_file("order-event.schema.json")["properties"]["order"]["$ref"] == order_id
    good = contract.openapi()["paths"]["/orders"]["get"]["responses"]["200"]["content"]["application/json"]["example"]
    order = good["items"][0]
    assert contract.validate(order, contract.component("Order")) == []
    event = {"event_id": "e1", "event": "order.paid", "store_id": "example-us", "order": order}
    assert contract.validate_file_schema(event, "order-event.schema.json") == []
    bad = dict(order, status="pending")
    assert contract.validate(bad, contract.component("Order"))
    assert contract.validate_file_schema(dict(event, order=bad), "order-event.schema.json")


def test_component_schemas_are_valid_2020_12():
    for schema in contract.openapi()["components"]["schemas"].values():
        Draft202012Validator.check_schema(schema)


def _examples(node, pointer=""):
    """Yield (example, schema_pointer) for every `example` in the document."""
    if isinstance(node, dict):
        if "example" in node:
            yield node["example"], (pointer + "/schema") if "schema" in node else pointer
        for key, value in node.items():
            if key != "example":
                yield from _examples(value, f"{pointer}/{str(key).replace('~', '~0').replace('/', '~1')}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _examples(value, f"{pointer}/{i}")


def test_every_example_validates_against_its_schema():
    found = list(_examples(contract.openapi()))
    assert found, "expected at least one example in openapi.yaml"
    for example, pointer in found:
        assert contract.validate(example, pointer) == [], pointer


def test_validate_reports_errors():
    assert contract.validate({"store_id": "x"}, contract.component("Store"))
    assert contract.validate({"x": 1}, contract.response_schema("/products"))


def test_date_time_requires_timezone():
    review = {"id": "r1", "rating": 5, "body": "ok", "created_at": "2026-01-01T00:00:00"}
    assert contract.validate(review, contract.component("Review"))
    review["created_at"] = "2026-01-01T00:00:00Z"
    assert contract.validate(review, contract.component("Review")) == []


@pytest.mark.skipif(not REPO_CONTRACT.exists(), reason="not inside the repository")
def test_bundled_copy_equals_repository_contract():
    """Refresh with `make sync-contract` when this fails."""
    repo = {p.relative_to(REPO_CONTRACT) for p in REPO_CONTRACT.rglob("*") if p.suffix in (".yaml", ".json")}
    bundled = {p.relative_to(BUNDLED) for p in BUNDLED.rglob("*") if p.suffix in (".yaml", ".json")}
    assert repo == bundled
    for rel in repo:
        assert (REPO_CONTRACT / rel).read_bytes() == (BUNDLED / rel).read_bytes(), (
            f"{rel} differs; run make sync-contract"
        )
    yaml.safe_load((BUNDLED / "openapi.yaml").read_text())
    for rel in bundled:
        if rel.suffix == ".json":
            json.loads((BUNDLED / rel).read_text())
