"""Item 2: GET /products and GET /products/{id}."""

from __future__ import annotations

import httpx

from .. import contract
from ..report import Result, check, fail, ok, skip, warn
from . import Context, body_json, describe, fetch, sid, text_in

ITEM = 2
LIST_SCHEMA = contract.response_schema("/products")
PRODUCT_SCHEMA = contract.component("Product")
REQUIRED = ["id", "url", "title", "description_html", "status", "updated_at", "images", "variants"]
FAR_FUTURE = "2999-01-01T00:00:00Z"
FAR_PAST = "1970-01-01T00:00:00Z"
PAGE = 5
MAX_PAGES = 3
BLOCKED_STATUSES = {401, 403, 429, 503}


def _get(ctx: Context, path: str, params: dict | None = None) -> httpx.Response | httpx.HTTPError:
    try:
        return ctx.client.api("GET", path, params=params)
    except httpx.HTTPError as exc:
        return exc


def _page(
    ctx: Context, name: str, params: dict, *, validate: bool = True
) -> tuple[dict | None, Result | None, httpx.Response | None]:
    """GET /products with params; returns (body, failure, response).

    The envelope (items list + next_cursor) is always checked; the full schema only when
    `validate`, so one schema defect is reported once rather than by every later check.
    """
    resp = _get(ctx, "/products", params)
    if not isinstance(resp, httpx.Response):
        return None, fail(ITEM, name, f"request failed: {resp}", resp), None
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
    first, failure, first_resp = _page(ctx, "2.products.schema", {"limit": PAGE}, validate=False)
    if failure:
        return [failure]
    assert first is not None and first_resp is not None
    items: list[dict] = [p for p in first["items"] if isinstance(p, dict)]
    ctx.products = items
    errors = contract.validate(first, LIST_SCHEMA)
    results.append(
        check(
            ITEM,
            "2.products.schema",
            not errors,
            "; ".join(errors),
            first_resp,
            ok_detail=f"{len(items)} products on the first page",
        )
    )
    results.append(check(ITEM, "2.products.limit", len(items) <= 5, f"limit=5 returned {len(items)} items", first_resp))
    results.append(_required(items, first_resp))
    results.append(_https(items, first_resp))
    results.append(_pagination(ctx, first))
    results.append(_updated_since(ctx))
    results.append(_updated_since_past(ctx, bool(items)))
    _, failure, _ = _page(ctx, "2.products.status_all", {"limit": PAGE, "status": "all"})
    results.append(failure or ok(ITEM, "2.products.status_all"))
    results.append(_stable(ctx, items))
    if not items:
        results.append(skip(ITEM, "2.products.get_one", "the store returned no products"))
        results.append(skip(ITEM, "2.products.public_page", "the store returned no products"))
        return results
    results.append(_get_one(ctx, items[0]))
    results.append(_not_found(ctx))
    results.append(public_page(ctx, items[0]))
    return results


def _required(items: list[dict], resp: httpx.Response) -> Result:
    missing = [
        f"{sid(p.get('id'))}: {[f for f in REQUIRED if f not in p]}" for p in items if any(f not in p for f in REQUIRED)
    ]
    return check(
        ITEM, "2.products.required_fields", not missing, "missing required fields: " + "; ".join(missing), resp
    )


def _https(items: list[dict], resp: httpx.Response) -> Result:
    bad = [str(p.get("url")) for p in items if not str(p.get("url", "")).startswith("https://")]
    return check(ITEM, "2.products.url_https", not bad, f"product url is not https: {bad}", resp)


def _pagination(ctx: Context, first: dict) -> Result:
    seen = [sid(p.get("id")) for p in first["items"]]
    cursor, pages = first["next_cursor"], 1
    if not cursor and len(first["items"]) >= PAGE:
        return _full_page_without_cursor(ctx, len(first["items"]))
    while cursor and pages < MAX_PAGES:
        data, failure, resp = _page(ctx, "2.products.pagination", {"limit": PAGE, "cursor": cursor})
        if failure:
            return failure
        assert data is not None
        ids = [sid(p.get("id")) for p in data["items"]]
        dupes = sorted(set(ids) & set(seen))
        if dupes:
            return fail(ITEM, "2.products.pagination", f"page {pages + 1} repeats ids already seen: {dupes}", resp)
        if not ids and data["next_cursor"]:
            return fail(ITEM, "2.products.pagination", "an empty page carries a next_cursor", resp)
        seen += ids
        cursor, pages = data["next_cursor"], pages + 1
    return ok(ITEM, "2.products.pagination", f"{pages} page(s), {len(seen)} distinct ids")


def _full_page_without_cursor(ctx: Context, first_count: int) -> Result:
    """A full page with next_cursor null is only right when the catalog is exactly that size."""
    data, failure, resp = _page(ctx, "2.products.pagination", {"limit": 250}, validate=False)
    if failure:
        return failure
    assert data is not None
    more = len(data["items"])
    if more > first_count:
        return fail(
            ITEM,
            "2.products.pagination",
            f"limit={PAGE} returned a full page with next_cursor null, but limit=250 returned {more} "
            "products: next_cursor must point at the rest",
            resp,
        )
    return ok(ITEM, "2.products.pagination", f"the catalog holds exactly {first_count} products")


def _updated_since_past(ctx: Context, has_products: bool) -> Result:
    name = "2.products.updated_since_past"
    data, failure, resp = _page(ctx, name, {"limit": PAGE, "updated_since": FAR_PAST}, validate=False)
    if failure:
        return failure
    assert data is not None
    return check(
        ITEM,
        name,
        bool(data["items"]) or not has_products,
        f"updated_since={FAR_PAST} returned no products although the store has some",
        resp,
    )


def _updated_since(ctx: Context) -> Result:
    data, failure, resp = _page(
        ctx, "2.products.updated_since", {"limit": PAGE, "updated_since": FAR_FUTURE}, validate=False
    )
    if failure:
        return failure
    assert data is not None
    return check(
        ITEM,
        "2.products.updated_since",
        not data["items"],
        f"updated_since={FAR_FUTURE} should return no items, got {len(data['items'])}",
        resp,
    )


def _stable(ctx: Context, items: list[dict]) -> Result:
    again, failure, resp = _page(ctx, "2.products.ids_stable", {"limit": PAGE}, validate=False)
    if failure:
        return failure
    assert again is not None
    before = [sid(p.get("id")) for p in items]
    after = [sid(p.get("id")) for p in again["items"]]
    return check(
        ITEM,
        "2.products.ids_stable",
        before == after,
        f"re-reading page 1 gave ids {after}, first read gave {before}",
        resp,
    )


def _get_one(ctx: Context, listed: dict) -> Result:
    name = "2.products.get_one"
    resp = _get(ctx, f"/products/{sid(listed.get('id'))}")
    if not isinstance(resp, httpx.Response):
        return fail(ITEM, name, f"request failed: {resp}", resp)
    if resp.status_code != 200:
        return fail(ITEM, name, f"expected 200, got {resp.status_code}", resp)
    data = body_json(resp)
    errors = contract.validate(data, PRODUCT_SCHEMA)
    if errors:
        return fail(ITEM, name, "; ".join(errors), resp)
    diffs = [
        f"{f}: list {listed.get(f)!r} vs one {data.get(f)!r}"
        for f in ("id", "title", "url")
        if sid(listed.get(f)) != sid(data.get(f))
    ]
    return check(ITEM, name, not diffs, "GET /products/{id} differs from the list record: " + "; ".join(diffs), resp)


def _not_found(ctx: Context) -> Result:
    resp = _get(ctx, f"/products/mervia-conformance-missing-{ctx.run_id}")
    if not isinstance(resp, httpx.Response):
        return fail(ITEM, "2.products.not_found", f"request failed: {resp}", resp)
    return check(
        ITEM,
        "2.products.not_found",
        resp.status_code == 404,
        f"an unknown product id should answer 404, got {resp.status_code}",
        resp,
    )


def public_page(ctx: Context, product: dict) -> Result:
    """The product url is https, final, and serves the title without auth."""
    name = "2.products.public_page"
    url = str(product.get("url", ""))
    title = str(product.get("title", ""))
    if not url.startswith("https://"):
        return fail(ITEM, name, f"product url is not https: {url!r}")
    resp = fetch(ctx, url)
    if not isinstance(resp, httpx.Response) or resp.status_code in BLOCKED_STATUSES:
        return warn(ITEM, name, f"could not fetch the public page ({describe(resp)}); check {url} by hand", resp)
    if 300 <= resp.status_code < 400:
        return fail(ITEM, name, f"product url redirects ({resp.status_code}); it must be the final URL", resp)
    if resp.status_code != 200:
        return fail(ITEM, name, f"public product page answered {resp.status_code}", resp)
    return check(ITEM, name, text_in(resp.text, title), f"public page does not contain the title {title!r}", resp)
