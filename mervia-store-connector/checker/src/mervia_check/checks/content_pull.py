"""Item 6, pull alternative (by arrangement with Mervia only; runs when the store declares content_pull):
the store's product page includes Mervia's document, server-side.

The checker plays Mervia's include endpoint with a local stub (`--include-stub-listen`, bound at
startup). The merchant points their staging store's include base URL at the stub for the run.
The checker then fetches product pages as raw HTML (no JavaScript runs):

1. ok: product A's page must carry the stub's document verbatim, including a run-unique token,
   so neither client-side rendering nor a copy cached before this run can pass.
2. slow: the stub holds product B, which the store has not fetched this run, for SLOW_SECONDS;
   the page must still answer within PAGE_BUDGET_SECONDS (a 1-second include timeout).
3. error: the stub answers 500 for product A; the page must keep A's last good copy. The
   contract lets the store cache A for 15 minutes, so a store that never re-fetches here gets a
   warning, not a pass: the phase then proved nothing.
4. error_no_copy: the stub answers 500 for product C, which the store has not fetched this run
   and so has no last good copy for; the page must still render, and the stub must have been
   called. This is the phase a cache cannot hide.
5. notfound: the stub answers 404; the page must still render.

Every include request must use the path /include/v1/<store key>/products/<contract product id>
and carry a Bearer token, and that token must never appear in page HTML.
"""

from __future__ import annotations

import time

import httpx

from ..report import Result, check, fail, ok, skip, warn
from ..stub.include_stub import IncludeStub
from . import Context, describe, fetch, first_products, in_head, no_product, page_text, retry, sample_product, sid
from .content_push import carries, ids_present

ITEM = 6
SLOW_SECONDS = 8.0
PAGE_BUDGET_SECONDS = 2.5


class _Pages:
    """Fetches product pages and remembers their HTML, to look for the include key afterwards."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.html: list[str] = []

    def get(self, url: str) -> tuple[httpx.Response | httpx.HTTPError, float]:
        started = time.monotonic()
        source = fetch(self.ctx, url)
        elapsed = time.monotonic() - started  # wall clock; includes at most one 0.5 s throttle gap
        self.html.append(page_text(source))
        return source, elapsed


def run(ctx: Context) -> list[Result]:
    stub = ctx.stub
    if stub is None:
        return [skip(ITEM, "6.pull.rendered", "pass --include-stub-listen HOST:PORT to test the pull include")]
    product, source = sample_product(ctx)
    if product is None:
        return [no_product(ctx, ITEM, "6.pull.rendered", source)]
    others = [p for p in first_products(ctx)[0] if sid(p.get("id")) != sid(product.get("id")) and p.get("url")]
    second = others[0] if others else None
    third = others[1] if len(others) > 1 else None
    stub.expect({sid(p.get("id")) for p in (product, second, third) if p is not None})
    stub.set_mode("ok")
    try:
        return _run(ctx, stub, product, second, third)
    finally:
        stub.set_mode("ok")


def _run(ctx: Context, stub: IncludeStub, product: dict, second: dict | None, third: dict | None) -> list[Result]:
    stub_url = f"http://{stub.address}/include/v1/"
    howto = (
        f"point the staging store's Mervia include base URL at {stub_url} for this run "
        "(replace 0.0.0.0 with an address the staging server can reach)"
    )
    pages = _Pages(ctx)
    url, pid = str(product.get("url", "")), sid(product.get("id"))
    doc = stub.document
    results: list[Result] = []

    page = retry(ctx, lambda: pages.get(url), lambda r: carries(r[0], doc))[0]
    if not carries(page, doc):
        seen = stub.count()
        why = "the stub received no request at all" if not seen else f"the stub received {seen} request(s)"
        results.append(
            fail(
                ITEM,
                "6.pull.rendered",
                f"the raw HTML of {url} does not carry this run's include document unchanged "
                f"(ids found: {ids_present(page_text(page))}, {describe(page)}); {why}. To run this check, {howto}. "
                "The include must be rendered on the server, not by browser JavaScript.",
                page,
            )
        )
        for mode in ("slow", "error", "error_no_copy", "notfound"):
            results.append(skip(ITEM, f"6.pull.{mode}", "not run: the page never rendered the stub's document"))
    else:
        results.append(ok(ITEM, "6.pull.rendered", f"product {pid}; stub called {stub.count(pid)} time(s)"))
        results.append(
            check(
                ITEM,
                "6.pull.in_head",
                in_head(page_text(page), doc["head_html"]),
                "head_html is not inside <head>",
                page,
            )
        )
        results.append(_slow(ctx, stub, pages, second))
        results.append(_error(stub, pages, url, pid, doc))
        results.append(_error_no_copy(stub, pages, third))
        results.append(_notfound(stub, pages, url, pid))
    return results + _requests(stub, pages)


def _slow(ctx: Context, stub: IncludeStub, pages: _Pages, second: dict | None) -> Result:
    name = "6.pull.slow"
    if second is None:
        return skip(ITEM, name, "needs a second product, one the store has not fetched this run")
    url, pid = str(second.get("url")), sid(second.get("id"))
    stub.set_mode("slow")
    before = stub.count(pid)
    source, elapsed = pages.get(url)
    calls = stub.count(pid) - before
    if not isinstance(source, httpx.Response) or source.status_code != 200:
        return fail(
            ITEM,
            name,
            f"with the include not answering, the page of product {pid} failed "
            f"({describe(source)}); render the page without the document",
            source,
        )
    if elapsed > PAGE_BUDGET_SECONDS:
        return fail(
            ITEM,
            name,
            f"the page of product {pid} took {elapsed:.1f}s while the include took "
            f"{SLOW_SECONDS:.0f}s to answer; use a 1-second include timeout",
            source,
        )
    if not calls:
        return warn(
            ITEM,
            name,
            f"the store did not call the include for product {pid}, so the timeout was not "
            "exercised (a copy cached before this run?)",
            source,
        )
    return ok(ITEM, name, f"product {pid}: page answered in {elapsed:.1f}s")


def _error(stub: IncludeStub, pages: _Pages, url: str, pid: str, doc: dict) -> Result:
    name = "6.pull.error"
    stub.set_mode("error")
    before = stub.count(pid)
    source, _ = pages.get(url)
    calls = stub.count(pid) - before
    detail = f"stub called {calls} time(s) in this phase"
    if not carries(source, doc):
        return fail(
            ITEM,
            name,
            f"with the include answering 500, the page lost the last good copy or failed "
            f"({describe(source)}); {detail}",
            source,
        )
    if not calls:
        return warn(
            ITEM,
            name,
            f"the page still carries the document, but the store did not call the include for product {pid} "
            "(the contract's 15-minute cache), so serving the last good copy on an error was not exercised; "
            "6.pull.error_no_copy covers the failure path, or re-run after the cache has expired",
            source,
        )
    return ok(ITEM, name, f"last good copy served; {detail}")


def _error_no_copy(stub: IncludeStub, pages: _Pages, third: dict | None) -> Result:
    """A 500 for a product the store has never fetched: no last good copy, and no cache to hide behind."""
    name = "6.pull.error_no_copy"
    if third is None:
        return skip(ITEM, name, "needs a third product, one the store has not fetched this run")
    url, pid = str(third.get("url")), sid(third.get("id"))
    stub.set_mode("error")
    before = stub.count(pid)
    source, _ = pages.get(url)
    calls = stub.count(pid) - before
    if not isinstance(source, httpx.Response) or source.status_code != 200:
        return fail(
            ITEM,
            name,
            f"with the include answering 500 and no last good copy, the page of product {pid} failed "
            f"({describe(source)}); render the page without the document",
            source,
        )
    if not calls:
        return warn(
            ITEM,
            name,
            f"the store did not call the include for product {pid}, so the failure path was not exercised "
            "(a copy cached before this run?)",
            source,
        )
    printed = "the ids are present (a copy from before this run?)" if ids_present(source.text) else "nothing printed"
    return ok(ITEM, name, f"product {pid}: page rendered with no copy to fall back on; {printed}")


def _notfound(stub: IncludeStub, pages: _Pages, url: str, pid: str) -> Result:
    stub.set_mode("notfound")
    before = stub.count(pid)
    source, _ = pages.get(url)
    calls = f"stub called {stub.count(pid) - before} time(s) in this phase"
    if isinstance(source, httpx.Response) and source.status_code == 200:
        still = "the ids are still present (cached copy)" if ids_present(source.text) else "the ids are gone"
        return ok(ITEM, "6.pull.notfound", f"page renders when nothing is live; {still}; {calls}")
    return fail(ITEM, "6.pull.notfound", f"with the include answering 404 the page failed ({describe(source)})", source)


def _requests(stub: IncludeStub, pages: _Pages) -> list[Result]:
    if not stub.requests:
        return [skip(ITEM, "6.pull.include_key", "the stub received no request to inspect")]
    bad_paths = sorted(
        {r.path for r in stub.requests if r.product_id is None or r.product_id not in (stub.expected or ())}
    )
    keyless = [r.path for r in stub.requests if not r.bearer]
    exposed = any(stub.bearer_in(html) for html in pages.html)
    return [
        check(
            ITEM,
            "6.pull.include_path",
            not bad_paths,
            f"include requests must use /include/v1/<store key>/products/<product id> with the id from the "
            f"products endpoint; the stub saw {bad_paths[:5]}",
        ),
        check(
            ITEM,
            "6.pull.include_key",
            not keyless,
            f"{len(keyless)} include request(s) carried no Authorization: Bearer token",
        ),
        check(
            ITEM,
            "6.pull.include_key_private",
            not exposed,
            "the include key sent to the stub appears in the product page HTML; it must stay on the server",
        ),
    ]
