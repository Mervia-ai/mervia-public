"""Load the bundled contract (OpenAPI document + webhook/include JSON Schemas) and validate against it.

The package carries its own copy of the repository's contract/ directory (refreshed with
`make sync-contract`), so an installed checker never depends on the checkout around it.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import cache
from importlib import resources
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

OPENAPI_URI = "urn:mervia:openapi"

FORMAT_CHECKER = FormatChecker()


@FORMAT_CHECKER.checks("date-time", raises=ValueError)
def _is_datetime(value: object) -> bool:
    """ISO 8601 with an explicit timezone, as the contract requires."""
    if not isinstance(value, str):
        return True
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return True


def _contract_dir() -> Any:
    return resources.files("mervia_check") / "contract"


@cache
def openapi() -> dict[str, Any]:
    text = (_contract_dir() / "openapi.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


@cache
def schema_file(name: str) -> dict[str, Any]:
    text = (_contract_dir() / "schemas" / name).read_text(encoding="utf-8")
    return json.loads(text)


def contract_version() -> str:
    return str(openapi()["info"]["version"])


def schema_files() -> list[str]:
    return sorted(p.name for p in (_contract_dir() / "schemas").iterdir() if p.name.endswith(".json"))


@cache
def _registry() -> Registry:
    """The OpenAPI document plus every schemas/*.json under its $id, so cross-file $refs resolve."""
    registry = Registry().with_resource(
        OPENAPI_URI, Resource.from_contents(openapi(), default_specification=DRAFT202012)
    )
    for name in schema_files():
        schema = schema_file(name)
        registry = registry.with_resource(
            schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012)
        )
    return registry


def _escape(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def component(name: str) -> str:
    """JSON pointer to a named component schema."""
    return f"/components/schemas/{name}"


def response_schema(path: str, method: str = "get", status: str = "200") -> str:
    """JSON pointer to the JSON response schema of an operation."""
    return f"/paths/{_escape(path)}/{method}/responses/{status}/content/application~1json/schema"


def _format_error(error: Any) -> str:
    where = "/".join(str(p) for p in error.absolute_path) or "(root)"
    return f"{where}: {error.message}"


def validate(instance: Any, pointer: str) -> list[str]:
    """Validate against the schema at `pointer` in openapi.yaml; return readable errors (max 10)."""
    validator = Draft202012Validator(
        {"$ref": f"{OPENAPI_URI}#{pointer}"}, registry=_registry(), format_checker=FORMAT_CHECKER
    )
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    return [_format_error(e) for e in errors[:10]]


def validate_file_schema(instance: Any, name: str) -> list[str]:
    """Validate against one of the standalone schemas in schemas/ (webhooks, include)."""
    validator = Draft202012Validator(schema_file(name), registry=_registry(), format_checker=FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    return [_format_error(e) for e in errors[:10]]


def enum(name: str) -> list[str]:
    return list(openapi()["components"]["schemas"][name]["enum"])
