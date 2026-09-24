"""Item 4: GET /pages (optional)."""

from __future__ import annotations

import httpx

from .. import contract
from ..report import Result, check, fail, ok
from . import Context, body_json

ITEM = 4


def run(ctx: Context) -> list[Result]:
    try:
        resp = ctx.client.api("GET", "/pages")
    except httpx.HTTPError as exc:
        return [fail(ITEM, "4.pages.schema", f"request failed: {exc}", exc)]
    if resp.status_code != 200:
        return [fail(ITEM, "4.pages.schema", f"expected 200, got {resp.status_code}", resp)]
    data = body_json(resp)
    kinds = contract.enum("PageKind")
    items = data.get("items") if isinstance(data, dict) else None
    bad = [p.get("kind") for p in items or [] if isinstance(p, dict) and p.get("kind") not in kinds]
    errors = contract.validate(data, contract.response_schema("/pages"))
    return [
        check(
            ITEM,
            "4.pages.schema",
            not errors,
            "; ".join(errors),
            resp,
            ok_detail=f"{len(items or [])} pages on the first page",
        ),
        check(ITEM, "4.pages.kinds", not bad, f"unknown kinds {bad}; allowed: {kinds}", resp)
        if items is not None
        else ok(ITEM, "4.pages.kinds", "no items to check"),
    ]
