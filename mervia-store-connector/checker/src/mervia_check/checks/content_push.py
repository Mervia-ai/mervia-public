"""Item 6 (push, the default delivery): PUT/DELETE /products/{id}/content and the server-rendered result.

The document carries a run-unique token in head_html and body_html, and both must appear in the
page verbatim ("printed unchanged"). A product whose page already carries Mervia's ids is left
alone unless named with --product-id, since the check deletes the stored document at the end.
"""

from __future__ import annotations

import json
import re
import time

import httpx

from ..report import Result, check, fail, ok, skip
from ..stub.include_stub import document
from . import Context, describe, fetch, in_head, no_product, page_text, retry, sample_product, seg, sid

ITEM = 6
IDS = ("mervia-product-schema", "mervia-shopping-guide")


def ids_present(page: str) -> list[str]:
    return [i for i in IDS if re.search(rf"""id\s*=\s*["']{i}["']""", page)]


_LD = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
_LD_TYPE = re.compile(r"""type\s*=\s*["']?application/ld\+json""", re.IGNORECASE)
_MERVIA_ID = re.compile(r"""id\s*=\s*["']?mervia-product-schema\b""", re.IGNORECASE)


def _types(node: object) -> list[str]:
    """Every @type in a JSON-LD value, following @graph and lists."""
    if isinstance(node, list):
        return [t for item in node for t in _types(item)]
    if not isinstance(node, dict):
        return []
    found = node.get("@type")
    here = found if isinstance(found, list) else [found] if isinstance(found, str) else []
    return here + _types(node.get("@graph", []))


def own_product_schemas(page: str) -> int:
    """JSON-LD blocks other than mervia-product-schema that describe a Product."""
    count = 0
    for attrs, body in _LD.findall(page):
        if not _LD_TYPE.search(attrs) or _MERVIA_ID.search(attrs):
            continue
        try:
            data = json.loads(body)
        except ValueError:
            continue
        if any(t in ("Product", "ProductGroup") for t in _types(data)):
            count += 1
    return count


def carries(source: httpx.Response | httpx.HTTPError, doc: dict) -> bool:
    """The page answered 200 with head_html and body_html printed verbatim."""
    return (
        isinstance(source, httpx.Response)
        and source.status_code == 200
        and doc["head_html"] in source.text
        and doc["body_html"] in source.text
    )


def cleared(source: httpx.Response | httpx.HTTPError) -> bool:
    return isinstance(source, httpx.Response) and source.status_code == 200 and not ids_present(source.text)


def run(ctx: Context) -> list[Result]:
    product, source = sample_product(ctx)
    if product is None:
        return [no_product(ctx, ITEM, "6.push.put", source)]
    pid, url = sid(product.get("id")), str(product.get("url", ""))
    path = f"/products/{seg(pid)}/content"
    before = fetch(ctx, url)
    if ids_present(page_text(before)) and not ctx.opts.product_id:
        return [
            skip(
                ITEM,
                "6.push.put",
                f"the page of product {pid} already carries Mervia's document ({url}); the check would delete it. "
                "Pass --product-id to use this product anyway, or name another one",
            )
        ]
    # Unix seconds, so this run's version is above any earlier one the store may have stored.
    doc = document(int(time.time()), ctx.run_id)
    results: list[Result] = []
    removed = False
    ctx.announce_writes()
    try:
        resp = ctx.client.api("PUT", path, json=doc)
        results.append(
            check(
                ITEM,
                "6.push.put",
                resp.status_code in (200, 204),
                f"expected 200 or 204, got {resp.status_code}",
                resp,
                ok_detail=f"product {pid}",
            )
        )
        if resp.status_code not in (200, 204):
            return results
        page = retry(ctx, lambda: fetch(ctx, url), lambda p: carries(p, doc))
        results.append(
            check(
                ITEM,
                "6.push.rendered",
                carries(page, doc),
                f"the raw HTML of {url} does not carry head_html and body_html unchanged "
                f"(ids found: {ids_present(page_text(page))}, {describe(page)}); "
                "the document must be printed as sent, on the server",
                page,
            )
        )
        if carries(page, doc):
            results.append(
                check(
                    ITEM,
                    "6.push.in_head",
                    in_head(page_text(page), doc["head_html"]),
                    "head_html is not inside <head>",
                    page,
                )
            )
            others = own_product_schemas(page_text(page))
            results.append(
                check(
                    ITEM,
                    "6.push.one_product_schema",
                    not others,
                    f"with mervia-product-schema printed, the page still carries {others} other Product "
                    "JSON-LD block(s); stop printing the store's own Product JSON-LD on that page "
                    "(one Product description per page)",
                    page,
                )
            )
        resp = ctx.client.api("DELETE", path)
        removed = resp.status_code in (200, 204)
        results.append(check(ITEM, "6.push.delete", removed, f"expected 200 or 204, got {resp.status_code}", resp))
        page = retry(ctx, lambda: fetch(ctx, url), cleared)
        results.append(
            check(
                ITEM,
                "6.push.removed",
                cleared(page),
                f"after DELETE, {url} still carries {ids_present(page_text(page))} "
                f"after {ctx.retries} retries ({describe(page)})",
                page,
            )
        )
    except httpx.HTTPError as exc:
        results.append(fail(ITEM, "6.push.request", f"request failed: {exc}", exc))
    finally:
        if not removed:
            results.append(_cleanup(ctx, path))
    return results


def _cleanup(ctx: Context, path: str) -> Result:
    try:
        resp = ctx.client.api("DELETE", path)
        if resp.status_code in (200, 204, 404):
            return ok(ITEM, "6.push.cleanup", "content document removed")
        detail = f"DELETE {path} answered {resp.status_code}"
    except httpx.HTTPError as exc:
        resp, detail = None, f"DELETE {path} failed: {exc}"
    ctx.say(f"CLEANUP FAILED: {detail}; remove the conformance document by hand.")
    return fail(ITEM, "6.push.cleanup", detail + "; remove the conformance document by hand", resp)
