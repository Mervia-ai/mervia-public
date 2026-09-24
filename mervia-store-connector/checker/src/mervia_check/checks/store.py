"""Item 1: GET /store — identity, declared capabilities, and 401 on a bad key."""

from __future__ import annotations

import secrets
import string

import httpx

from .. import contract
from ..report import Result, check, fail, ok, warn
from . import Context, body_json, sid

ITEM = 1


def run(ctx: Context) -> list[Result]:
    results: list[Result] = []
    try:
        resp = ctx.client.api("GET", "/store")
    except httpx.HTTPError as exc:
        return [fail(ITEM, "1.store.status", f"request failed: {exc}", exc)]
    results.append(
        check(ITEM, "1.store.status", resp.status_code == 200, f"expected 200, got {resp.status_code}", resp)
    )
    data = body_json(resp)
    if resp.status_code == 200:
        errors = contract.validate(data, contract.response_schema("/store"))
        results.append(check(ITEM, "1.store.schema", not errors, "; ".join(errors), resp))
    if isinstance(data, dict):
        results.append(_capabilities(data, resp))
        if ctx.opts.store_id is not None:
            got = sid(data.get("store_id"))
            results.append(
                check(
                    ITEM,
                    "1.store.store_id",
                    got == ctx.opts.store_id,
                    f"store_id is {got!r}, expected {ctx.opts.store_id!r} (--store-id)",
                    resp,
                )
            )
    results += _auth(ctx)
    return results


def _capabilities(data: dict, resp: httpx.Response) -> Result:
    caps = data.get("capabilities")
    if not isinstance(caps, list):
        return fail(ITEM, "1.store.capabilities", "capabilities is missing or not a list", resp)
    known = contract.enum("Capability")
    unknown = [c for c in caps if c not in known]
    if unknown:
        return fail(ITEM, "1.store.capabilities", f"unknown capabilities {unknown}; allowed: {known}", resp)
    if "content_pull" in caps and "content_push" in caps:
        return fail(ITEM, "1.store.capabilities", "content_pull and content_push are mutually exclusive", resp)
    return ok(ITEM, "1.store.capabilities", ", ".join(caps) or "(none declared)")


def probe_key(key: str) -> str:
    """A random key of the same length, never equal to the real one."""
    alphabet = string.ascii_letters + string.digits
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(len(key)))
        if candidate != key:
            return candidate


def _probes(ctx: Context) -> list[tuple[str, str, str, dict]]:
    """(result name, method, path, client kwargs) for every 401 probe that applies to this store."""
    wrong = probe_key(ctx.client.key)
    ctx.redact.add(wrong)
    missing = f"/articles/mervia-conformance-missing-{ctx.run_id}"
    probes = [
        ("1.store.auth.wrong_key", "GET", "/store", {"key": wrong}),
        ("1.store.auth.no_key", "GET", "/store", {"auth": False}),
    ]
    if "products" in ctx.capabilities:
        probes.append(("1.store.auth.no_key.products", "GET", "/products", {"auth": False}))
    if "orders" in ctx.capabilities:
        probes.append(("1.store.auth.no_key.orders", "GET", "/orders", {"auth": False}))
    if "articles" in ctx.capabilities:
        probes += [
            ("1.store.auth.no_key.articles", "GET", "/articles", {"auth": False}),
            ("1.store.auth.no_key.article_patch", "PATCH", missing, {"auth": False, "json": {"status": "hidden"}}),
            ("1.store.auth.no_key.article_delete", "DELETE", missing, {"auth": False}),
        ]
    return probes


def _auth(ctx: Context) -> list[Result]:
    """A missing or wrong key answers 401 on every endpoint, before any lookup (so never 404)."""
    results: list[Result] = []
    for name, method, path, kwargs in _probes(ctx):
        try:
            resp = ctx.client.api(method, path, **kwargs)
        except httpx.HTTPError as exc:
            results.append(fail(ITEM, name, f"request failed: {exc}", exc))
            continue
        if resp.status_code != 401:
            results.append(
                fail(ITEM, name, f"{method} {path} without a valid key: expected 401, got {resp.status_code}", resp)
            )
        elif contract.validate(body_json(resp), contract.component("Error")):
            results.append(warn(ITEM, name, '401 body is not {"error": "<code>", "message": "<text>"}', resp))
        else:
            results.append(ok(ITEM, name))
    return results
