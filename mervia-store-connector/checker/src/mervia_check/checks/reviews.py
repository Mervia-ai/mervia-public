"""Item 3: GET /products/{id}/reviews."""

from __future__ import annotations

import httpx

from .. import contract
from ..report import Result, check, fail, ok, warn
from . import Context, body_json, first_products, no_product, sample_product, seg, sid

ITEM = 3
SCHEMA = contract.response_schema("/products/{id}/reviews")
MAX_PAGES = 20


def _pick(ctx: Context) -> tuple[dict | None, httpx.Response | httpx.HTTPError | None]:
    """--product-id, else the first product with rating.count > 0, else the first product."""
    if ctx.opts.product_id:
        return sample_product(ctx)
    products, source = first_products(ctx)
    rated = [p for p in products if isinstance(p.get("rating"), dict) and (p["rating"].get("count") or 0) > 0]
    return (rated or products or [None])[0], source


def run(ctx: Context) -> list[Result]:
    product, source = _pick(ctx)
    if product is None:
        return [no_product(ctx, ITEM, "3.reviews.schema", source)]
    path = f"/products/{seg(product.get('id'))}/reviews"
    reviews: list[dict] = []
    summary: dict = {}
    cursor: str | None = None
    last: httpx.Response | None = None
    for _ in range(MAX_PAGES):
        try:
            resp = ctx.client.api("GET", path, params={"limit": 100, **({"cursor": cursor} if cursor else {})})
        except httpx.HTTPError as exc:
            return [fail(ITEM, "3.reviews.schema", f"request failed: {exc}", exc)]
        if resp.status_code != 200:
            return [fail(ITEM, "3.reviews.schema", f"expected 200, got {resp.status_code}", resp)]
        data = body_json(resp)
        errors = contract.validate(data, SCHEMA)
        if errors:
            return [fail(ITEM, "3.reviews.schema", "; ".join(errors), resp)]
        reviews += data["items"]
        summary, cursor, last = data["summary"], data["next_cursor"], resp
        if not cursor:
            break
    assert last is not None
    read = f"product {sid(product.get('id'))}: {len(reviews)} reviews read"
    results = [
        ok(ITEM, "3.reviews.schema", read)
        if reviews
        else warn(ITEM, "3.reviews.schema", f"{read}; with no reviews the checks below prove little", last)
    ]
    results.append(
        check(
            ITEM,
            "3.reviews.summary_count",
            summary.get("count", 0) >= len(reviews),
            f"summary.count {summary.get('count')} is below the {len(reviews)} reviews returned",
            last,
        )
    )
    emails = [r.get("author_display_name") for r in reviews if "@" in str(r.get("author_display_name", ""))]
    results.append(
        check(
            ITEM,
            "3.reviews.no_email",
            not emails,
            f"{len(emails)} author_display_name value(s) contain '@'; send a display name, never an email",
            last,
        )
    )
    return results
