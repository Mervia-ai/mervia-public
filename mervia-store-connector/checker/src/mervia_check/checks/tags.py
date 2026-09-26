"""Item 7 (tracking tag) and item 9 (Search Console verification tag), read from public HTML."""

from __future__ import annotations

import re

import httpx

from ..report import Result, check, fail, ok, skip
from . import Context, describe, fetch, first_products, is_ok_page, page_text, public_base

# One tag src per Mervia environment; a run accepts exactly the one for --mervia-env.
TAG_SRCS = {
    "production": "https://app.mervia.ai/tag/v1/mervia.js",
    "staging": "https://staging-marketing.mervia.ai/tag/v1/mervia.js",
}
TAG_SRC = TAG_SRCS["production"]
_SCRIPT = re.compile(r"<script\b([^>]*)>", re.IGNORECASE)
_META = re.compile(r"<meta\b([^>]*)>", re.IGNORECASE)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_ATTR = re.compile(r"""([\w:.-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?""")


def attributes(raw: str) -> dict[str, str]:
    """Attributes of one tag, in any order and quoting style."""
    return {m.group(1).lower(): m.group(2) or m.group(3) or m.group(4) or "" for m in _ATTR.finditer(raw)}


def live_html(page: str) -> str:
    """The page without HTML comments: a commented-out tag is not a tag."""
    return _COMMENT.sub("", page)


def mervia_tags(page: str, src: str = TAG_SRC) -> list[dict[str, str]]:
    return [a for a in map(attributes, _SCRIPT.findall(live_html(page))) if a.get("src") == src]


def tag_src(ctx: Context) -> str:
    return TAG_SRCS[ctx.opts.mervia_env]


def _other_env(page: str, env: str) -> str | None:
    """The other environment whose tag the page carries instead, if any."""
    return next((e for e, s in TAG_SRCS.items() if e != env and mervia_tags(page, s)), None)


def _home(ctx: Context) -> tuple[str | None, httpx.Response | httpx.HTTPError | None]:
    base = public_base(ctx)
    return (None, None) if base is None else (base + "/", fetch(ctx, base + "/"))


def run_tag(ctx: Context) -> list[Result]:
    url, home = _home(ctx)
    if url is None or home is None:
        return [fail(7, "7.tag.present", "no public site to read: pass --public-base-url")]
    if not is_ok_page(home):
        return [fail(7, "7.tag.present", f"could not fetch the home page {url} ({describe(home)})", home)]
    src, env = tag_src(ctx), ctx.opts.mervia_env
    tags = mervia_tags(page_text(home), src)
    present = bool(tags) and bool(tags[0].get("data-store"))
    missing = f'no <script src="{src}" data-store="..."> on {url}'
    other = None if tags else _other_env(page_text(home), env)
    if other:
        missing += (
            f"; the page carries Mervia's {other} tag instead. A store uses the tag of the Mervia environment "
            f"it connects to; this run checks {env} (--mervia-env)"
        )
    results = [check(7, "7.tag.present", present, missing, home, ok_detail=f"{env} tag")]
    if present and ctx.opts.store_id is not None:
        got = tags[0].get("data-store")
        results.append(
            check(
                7,
                "7.tag.store_id",
                got == ctx.opts.store_id,
                f"data-store is {got!r}, expected {ctx.opts.store_id!r} (--store-id)",
                home,
            )
        )
    if "products" in ctx.capabilities:
        products, _ = first_products(ctx)
        if products and products[0].get("url"):
            page = fetch(ctx, str(products[0]["url"]))
            results.append(
                check(
                    7,
                    "7.tag.product_page",
                    is_ok_page(page) and bool(mervia_tags(page_text(page), src)),
                    f"the tag is not on the product page {products[0]['url']} ({describe(page)}); "
                    "it belongs on every page",
                    page,
                )
            )
    return results


def run_search_console(ctx: Context) -> list[Result]:
    url, home = _home(ctx)
    if url is None or home is None or not is_ok_page(home):
        return [skip(9, "9.search_console.meta", f"could not fetch the home page ({describe(home)})")]
    for attrs in map(attributes, _META.findall(live_html(page_text(home)))):
        if attrs.get("name") == "google-site-verification" and attrs.get("content"):
            return [ok(9, "9.search_console.meta", f"content={attrs['content']!r}")]
    return [skip(9, "9.search_console.meta", "not yet placed (Mervia sends the tag later)")]
