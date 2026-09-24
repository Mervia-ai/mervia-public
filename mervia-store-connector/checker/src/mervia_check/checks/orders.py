"""Item 8: GET /orders — the paid orders Mervia reads about once an hour for attribution."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .. import contract
from ..report import Result, check, fail, ok, warn
from . import Context, body_json, sid

ITEM = 8
LIST_SCHEMA = contract.response_schema("/orders")
REQUIRED = ["id", "status", "paid_at", "updated_at", "currency", "total", "refunded_total", "line_items"]
STATUSES = ("paid", "refunded", "cancelled")
PII_FRAGMENTS = ("email", "name", "phone", "address")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
FAR_FUTURE = "2999-01-01T00:00:00Z"
FAR_PAST = "1970-01-01T00:00:00Z"
PAGE = 5
MAX_PAGES = 3


def _page(
    ctx: Context, name: str, params: dict, *, validate: bool = True
) -> tuple[dict | None, Result | None, httpx.Response | None]:
    """GET /orders with params; returns (body, failure, response)."""
    try:
        resp = ctx.client.api("GET", "/orders", params=params)
    except httpx.HTTPError as exc:
        return None, fail(ITEM, name, f"request failed: {exc}", exc), None
    if resp.status_code != 200:
        return None, fail(ITEM, name, f"expected 200, got {resp.status_code}", resp), resp
    data = body_json(resp)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list) or "next_cursor" not in data:
        return None, fail(ITEM, name, 'the body is not {"items": [...], "next_cursor": ...}', resp), resp
    errors = contract.validate(data, LIST_SCHEMA) if validate else []
    if errors:
        return None, fail(ITEM, name, "; ".join(errors), resp), resp
    return data, None, resp


def run(ctx: Context) -> list[Result]:
    results: list[Result] = []
    first, failure, resp = _page(ctx, "8.orders.schema", {"limit": PAGE}, validate=False)
    if failure:
        return [failure]
    assert first is not None and resp is not None
    items = [o for o in first["items"] if isinstance(o, dict)]
    errors = contract.validate(first, LIST_SCHEMA)
    if errors:
        results.append(fail(ITEM, "8.orders.schema", "; ".join(errors), resp))
    elif not items:
        results.append(
            warn(
                ITEM,
                "8.orders.schema",
                "GET /orders returned no orders, so the checks below prove little; place and pay a test "
                "order on staging and run again",
                resp,
            )
        )
    else:
        results.append(ok(ITEM, "8.orders.schema", f"{len(items)} orders on the first page"))
    results.append(check(ITEM, "8.orders.limit", len(items) <= PAGE, f"limit={PAGE} returned {len(items)} items", resp))
    results.append(_required(items, resp))
    results.append(_paid_only(items, resp))
    results.append(_amounts(items, resp))
    results.append(_no_pii(items, resp))
    results.append(_pagination(ctx, first))
    results.append(_updated_since(ctx))
    results.append(_updated_since_past(ctx, bool(items)))
    return results


def _required(items: list[dict], resp: httpx.Response) -> Result:
    missing = [
        f"{sid(o.get('id'))}: {[f for f in REQUIRED if f not in o]}" for o in items if any(f not in o for f in REQUIRED)
    ]
    return check(ITEM, "8.orders.required_fields", not missing, "missing required fields: " + "; ".join(missing), resp)


def _paid_only(items: list[dict], resp: httpx.Response) -> Result:
    """Every listed order has been paid: a status of paid, refunded or cancelled, and a paid_at."""
    bad = [
        f"{sid(o.get('id'))}: status={o.get('status')!r}, paid_at={o.get('paid_at')!r}"
        for o in items
        if o.get("status") not in STATUSES or not o.get("paid_at")
    ]
    return check(
        ITEM,
        "8.orders.paid_only",
        not bad,
        "only orders that have been paid belong in the list, with status paid, refunded or cancelled: "
        + "; ".join(bad),
        resp,
    )


def _money(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _amounts(items: list[dict], resp: httpx.Response) -> Result:
    """0 <= refunded_total <= total; a cancelled order is a full refund."""
    name = "8.orders.refunded_total"
    bad, partial_cancel = [], []
    for o in items:
        total, refunded = _money(o.get("total")), _money(o.get("refunded_total"))
        if total is None or refunded is None:
            continue  # the schema check reports a malformed amount
        if refunded < 0 or refunded > total:
            bad.append(f"{sid(o.get('id'))}: refunded_total {refunded} with total {total}")
        elif o.get("status") == "cancelled" and refunded != total:
            partial_cancel.append(f"{sid(o.get('id'))}: cancelled with refunded_total {refunded} of {total}")
    if bad:
        return fail(
            ITEM,
            name,
            "refunded_total must be between 0 and total (a running total, not a delta): " + "; ".join(bad),
            resp,
        )
    if partial_cancel:
        return warn(
            ITEM,
            name,
            "a cancelled order counts as a full refund, so Mervia records refunded_total = total for it: "
            + "; ".join(partial_cancel),
            resp,
        )
    return ok(ITEM, name)


def _pii_paths(value: Any, path: str) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, inner in value.items():
            here = f"{path}.{key}" if path else str(key)
            if any(fragment in str(key).lower() for fragment in PII_FRAGMENTS):
                found.append(f"{here} (key)")
            found += _pii_paths(inner, here)
    elif isinstance(value, list):
        for i, inner in enumerate(value):
            found += _pii_paths(inner, f"{path}[{i}]")
    elif isinstance(value, str) and EMAIL.search(value):
        found.append(f"{path} (email address)")
    return found


def _no_pii(items: list[dict], resp: httpx.Response) -> Result:
    found = [p for o in items for p in _pii_paths(o, sid(o.get("id")))]
    return check(
        ITEM,
        "8.orders.no_pii",
        not found,
        "no customer name, email, phone or address may be returned; found: " + "; ".join(found[:10]),
        resp,
    )


def _pagination(ctx: Context, first: dict) -> Result:
    name = "8.orders.pagination"
    seen = [sid(o.get("id")) for o in first["items"]]
    cursor, pages = first["next_cursor"], 1
    if not cursor and len(first["items"]) >= PAGE:
        data, failure, resp = _page(ctx, name, {"limit": 250}, validate=False)
        if failure:
            return failure
        assert data is not None
        if len(data["items"]) > len(first["items"]):
            return fail(
                ITEM,
                name,
                f"limit={PAGE} returned a full page with next_cursor null, but limit=250 returned "
                f"{len(data['items'])} orders: next_cursor must point at the rest",
                resp,
            )
        return ok(ITEM, name, f"the store holds exactly {len(first['items'])} paid orders")
    while cursor and pages < MAX_PAGES:
        data, failure, resp = _page(ctx, name, {"limit": PAGE, "cursor": cursor})
        if failure:
            return failure
        assert data is not None
        ids = [sid(o.get("id")) for o in data["items"]]
        dupes = sorted(set(ids) & set(seen))
        if dupes:
            return fail(ITEM, name, f"page {pages + 1} repeats ids already seen: {dupes}", resp)
        if not ids and data["next_cursor"]:
            return fail(ITEM, name, "an empty page carries a next_cursor", resp)
        seen += ids
        cursor, pages = data["next_cursor"], pages + 1
    return ok(ITEM, name, f"{pages} page(s), {len(seen)} distinct ids")


def _updated_since(ctx: Context) -> Result:
    name = "8.orders.updated_since"
    data, failure, resp = _page(ctx, name, {"limit": PAGE, "updated_since": FAR_FUTURE}, validate=False)
    if failure:
        return failure
    assert data is not None
    return check(
        ITEM,
        name,
        not data["items"],
        f"updated_since={FAR_FUTURE} should return no orders, got {len(data['items'])}; Mervia reads with "
        "updated_since set to its last read, so it must be honoured",
        resp,
    )


def _updated_since_past(ctx: Context, has_orders: bool) -> Result:
    name = "8.orders.updated_since_past"
    data, failure, resp = _page(ctx, name, {"limit": PAGE, "updated_since": FAR_PAST}, validate=False)
    if failure:
        return failure
    assert data is not None
    return check(
        ITEM,
        name,
        bool(data["items"]) or not has_orders,
        f"updated_since={FAR_PAST} returned no orders although the store has some",
        resp,
    )
