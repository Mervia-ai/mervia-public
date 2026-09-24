"""Shared context and helpers for the per-item checks.

Each check module exposes `run(ctx) -> list[Result]`. Checks never raise for a store's
misbehaviour; they turn it into a failing Result carrying the request and response.
"""

from __future__ import annotations

import html
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import urljoin, urlsplit

import httpx

from ..client import Client
from ..redact import Redactor
from ..report import Result, fail, skip

if TYPE_CHECKING:
    from ..receiver.webhook_receiver import WebhookReceiver
    from ..stub.include_stub import IncludeStub

CONFORMANCE_TAG = "mervia-conformance"
T = TypeVar("T")


def stderr(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


@dataclass
class Options:
    base_url: str
    api_key: str = field(repr=False)
    store_id: str | None = None
    items: list[int] | None = None
    public_base_url: str | None = None
    product_id: str | None = None
    webhook_secret: str | None = field(default=None, repr=False)
    webhook_listen: str = "0.0.0.0:8788"
    webhook_timeout: float = 300.0
    include_stub_listen: str | None = None
    content_mode: str = "auto"
    timeout: float = 10.0
    insecure: bool = False
    public_auth: str | None = field(default=None, repr=False)
    allow_writes: bool = False
    allow_http: bool = False


@dataclass
class Context:
    opts: Options
    client: Client
    run_id: str
    store: dict[str, Any] | None = None
    products: list[dict[str, Any]] | None = None
    sleep: Callable[[float], None] = time.sleep
    retry_delay: float = 5.0
    retries: int = 3
    say: Callable[[str], None] = stderr
    redact: Redactor = field(default_factory=Redactor)
    store_response: httpx.Response | None = None
    receiver: WebhookReceiver | None = None
    stub: IncludeStub | None = None
    announced_writes: bool = False

    def announce_writes(self) -> None:
        """A loud banner before the first write of the run."""
        if self.announced_writes:
            return
        self.announced_writes = True
        host = urlsplit(self.opts.base_url).netloc
        rule = "=" * 72
        self.say(
            f"{rule}\n  mervia-check is about to WRITE to {host}\n"
            "  (a test article, a product-page document; all tagged mervia-conformance and removed).\n"
            f"  This must be a STAGING store. Stop now (Ctrl-C) if it is not.\n{rule}"
        )

    @property
    def capabilities(self) -> list[str]:
        caps = (self.store or {}).get("capabilities")
        return [c for c in caps if isinstance(c, str)] if isinstance(caps, list) else []


def body_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def sid(value: Any) -> str:
    """Ids are opaque strings; an integer id is treated as its decimal string."""
    return str(value)


def text_in(page: str, text: str) -> bool:
    """`text` appears in the HTML either verbatim or HTML-escaped."""
    return text in page or html.escape(text) in page or html.escape(text, quote=False) in page


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def public_base(ctx: Context) -> str | None:
    """--public-base-url, else the store's primary_host over https."""
    if ctx.opts.public_base_url:
        return ctx.opts.public_base_url.rstrip("/")
    host = (ctx.store or {}).get("primary_host")
    return f"https://{host}" if isinstance(host, str) and host else None


def fetch(ctx: Context, url: str, *, auth: bool = False) -> httpx.Response | httpx.HTTPError:
    try:
        return ctx.client.fetch(url, auth=auth)
    except httpx.HTTPError as exc:
        return exc


def retry(ctx: Context, attempt: Callable[[], T], done: Callable[[T], bool]) -> T:
    """Run `attempt` until `done(result)`, up to `ctx.retries` extra tries `ctx.retry_delay` apart."""
    result = attempt()
    for _ in range(ctx.retries):
        if done(result):
            break
        ctx.sleep(ctx.retry_delay)
        result = attempt()
    return result


def first_products(ctx: Context) -> tuple[list[dict[str, Any]], httpx.Response | httpx.HTTPError | None]:
    """The first page of products (limit 5), cached on the context."""
    if ctx.products is not None:
        return ctx.products, None
    try:
        resp = ctx.client.api("GET", "/products", params={"limit": 5})
    except httpx.HTTPError as exc:
        return [], exc
    data = body_json(resp)
    items = data.get("items") if resp.status_code == 200 and isinstance(data, dict) else None
    ctx.products = [p for p in items if isinstance(p, dict)] if isinstance(items, list) else []
    return ctx.products, resp


def sample_product(ctx: Context) -> tuple[dict[str, Any] | None, httpx.Response | httpx.HTTPError | None]:
    """--product-id if given, else the first listed product."""
    if ctx.opts.product_id:
        try:
            resp = ctx.client.api("GET", f"/products/{ctx.opts.product_id}")
        except httpx.HTTPError as exc:
            return None, exc
        data = body_json(resp)
        return (data if resp.status_code == 200 and isinstance(data, dict) else None), resp
    products, source = first_products(ctx)
    return (products[0] if products else None), source


def no_product(ctx: Context, item: int, name: str, source: httpx.Response | httpx.HTTPError | None) -> Result:
    """A missing sample product: FAIL when --product-id named one that does not exist, else SKIP."""
    if ctx.opts.product_id:
        return fail(
            item,
            name,
            f"--product-id {ctx.opts.product_id}: the product could not be read ({describe(source)})",
            source,
        )
    return skip(item, name, f"no product to test with ({describe(source)})")


def is_ok_page(source: httpx.Response | httpx.HTTPError) -> bool:
    return isinstance(source, httpx.Response) and source.status_code == 200


def page_text(source: httpx.Response | httpx.HTTPError) -> str:
    return source.text if isinstance(source, httpx.Response) else ""


def describe(source: httpx.Response | httpx.HTTPError | None) -> str:
    if source is None:
        return "no request made"
    if isinstance(source, httpx.Response):
        return f"HTTP {source.status_code}"
    return f"{type(source).__name__}: {source}"


_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)
SITEMAP_CHILD_LIMIT = 50


@dataclass
class Sitemap:
    urls: set[str] | None  # None: the root sitemap could not be read
    source: httpx.Response | httpx.HTTPError
    child_failures: int = 0


def sitemap_urls(ctx: Context, base: str) -> Sitemap:
    """Every <loc> in <base>/sitemap.xml, following a sitemap index one level down."""
    root = fetch(ctx, base.rstrip("/") + "/sitemap.xml")
    if not is_ok_page(root):
        return Sitemap(None, root)
    body = page_text(root)
    locs = {html.unescape(m) for m in _LOC.findall(body)}
    if "<sitemapindex" not in body:
        return Sitemap(locs, root)
    found: set[str] = set()
    failures = 0
    for child in sorted(locs)[:SITEMAP_CHILD_LIMIT]:
        child_resp = fetch(ctx, urljoin(base + "/", child))
        if is_ok_page(child_resp):
            found |= {html.unescape(m) for m in _LOC.findall(page_text(child_resp))}
        else:
            failures += 1
    return Sitemap(found, root, failures)


def url_in(url: str, urls: set[str]) -> bool:
    """Sitemap membership, tolerant of a trailing slash."""
    wanted = url.rstrip("/")
    return any(u.rstrip("/") == wanted for u in urls)


_HEAD_END = re.compile(r"</head\s*>", re.IGNORECASE)


def in_head(page: str, marker: str) -> bool:
    """`marker` appears before the closing </head>."""
    end = _HEAD_END.search(page)
    return end is not None and marker in page[: end.start()]
