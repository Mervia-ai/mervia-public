"""An in-process store that implements the contract well enough for every check to pass.

`breaks` names deliberate defects, one per check, so the tests can prove the checker catches
each kind of breakage. Served through httpx.MockTransport: API under API, storefront under BASE.
The pull include is fetched over real localhost HTTP from the checker's stub.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

BASE = "https://staging.example.com"
API = BASE + "/api/mervia/v1"
KEY = "test-key-123"
INCLUDE_KEY = "include-key-456"
STORE_ID = "example-us"
PUBLIC_AUTH = ("stageuser", "hunter2pass")
TAG_SRC = "https://app.mervia.ai/tag/v1/mervia.js"
DEFAULT_CAPS = ["products", "reviews", "articles", "pages", "orders", "content_push"]
WEBHOOK_CAPS = DEFAULT_CAPS + ["order_webhook", "product_webhook"]  # by arrangement with Mervia


def now() -> str:
    return datetime.now(UTC).isoformat()


def digest(body: str) -> str:
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


def J(status: int, body: Any) -> httpx.Response:  # noqa: N802
    return httpx.Response(status, json=body)


def H(status: int, body: str) -> httpx.Response:  # noqa: N802
    return httpx.Response(status, text=body, headers={"Content-Type": "text/html; charset=utf-8"})


class FakeStore:
    def __init__(
        self,
        caps: list[str] | None = None,
        breaks: tuple[str, ...] = (),
        include_url: str | None = None,
        include_cache: bool = False,
    ):
        self.caps = list(DEFAULT_CAPS if caps is None else caps)
        self.breaks = set(breaks)
        self.include_url = include_url
        self.include_cache = include_cache  # the contract's 15-minute cache: one fetch per product per run
        self.include_outcomes: dict[str, str] = {}
        self.include_last_good: dict[str, dict] = {}
        self.products = [self._product(i) for i in range(1, 8)]
        self.orders = [self._order(i) for i in range(1, 8)]
        self.content: dict[str, dict] = {}
        self.ever_published: set[str] = set()
        self.unstable_done = False
        self.auth_headers: list[str | None] = []
        self.articles: dict[str, dict] = {
            # the store's own post, which the tag filter must leave out
            "art-0": {
                "id": "art-0",
                "type": "post",
                "title": "Hello",
                "slug": "hello",
                "url": f"{BASE}/blogs/news/hello",
                "body_html": "<p>hi</p>",
                "tags": ["news"],
                "status": "published",
                "published_at": now(),
                "created_at": now(),
                "updated_at": now(),
                "content_digest": digest("<p>hi</p>"),
            }
        }

    @property
    def conformance_articles(self) -> dict[str, dict]:
        return {k: a for k, a in self.articles.items() if "mervia-conformance" in a["tags"]}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    # -- data ------------------------------------------------------------------------------
    def _product(self, i: int) -> dict:
        handle = f"widget-{i}"
        return {
            "id": 100 + i,  # integer ids are allowed and read as strings
            "handle": handle,
            "url": f"{BASE}/products/{handle}",
            "title": f"Example Widget {i} & Co",
            "description_html": "<p>An example widget.</p>",
            "status": "active",
            "updated_at": "2026-09-01T00:00:00Z",
            "images": [{"url": f"https://cdn.example.com/{handle}.jpg", "position": 1}],
            "variants": [{"id": 1000 + i, "price": "129.00", "currency": "USD", "available": True}],
            "rating": {"average": 4.5, "count": 3 if i == 2 else 0},
        }

    def _order(self, i: int) -> dict:
        status = {3: "refunded", 5: "cancelled"}.get(i, "paid")
        refunded = {"paid": "0.00", "refunded": "20.00", "cancelled": "136.16"}[status]
        if status == "cancelled" and "orders_cancel_partial" in self.breaks:
            refunded = "10.00"
        if "orders_refund_over" in self.breaks and i == 1:
            refunded = "999.00"
        order = {
            "id": 10040 + i,
            "number": f"#{10040 + i}",
            "status": status,
            "paid_at": f"2026-09-{10 + i:02d}T10:00:00Z",
            "updated_at": f"2026-09-{10 + i:02d}T{12 if status == 'paid' else 15}:00:00Z",
            "currency": "USD",
            "subtotal": "129.50",
            "discount_total": "10.00",
            "shipping": "5.00",
            "tax": "11.66",
            "total": "136.16",
            "refunded_total": refunded,
            "line_items": [{"product_id": 101, "variant_id": 1001, "sku": "EX-M1", "quantity": 1, "price": "129.50"}],
            "mervia_attribution": "v1.9f2c1a7b" if i % 2 else None,
        }
        if "orders_pii" in self.breaks and i == 2:
            order["customer_email"] = "jane@example.com"
        if "orders_unpaid" in self.breaks and i == 4:
            order["status"] = "pending"
        return order

    def list_orders(self, q: dict[str, list[str]]) -> httpx.Response:
        limit = int(q.get("limit", ["250"])[0])
        offset = int(q.get("cursor", ["0"])[0])
        items = self.orders
        since = q.get("updated_since", [""])[0]
        if since and "orders_ignore_updated_since" not in self.breaks:
            items = [o for o in items if o["updated_at"] >= since]
        page = items[offset : offset + limit]
        more = offset + limit < len(items) and "orders_no_cursor" not in self.breaks
        return J(200, {"items": page, "next_cursor": str(offset + limit) if more else None})

    def product_view(self, p: dict) -> dict:
        p = dict(p)
        if "http_url" in self.breaks:
            p["url"] = p["url"].replace("https://", "http://")
        return p

    # -- routing ---------------------------------------------------------------------------
    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url).replace("http://", "https://", 1)  # serve --allow-http runs too
        if url.startswith(API):
            return self.api(request, url[len(API) :].split("?")[0], parse_qs(urlsplit(url).query))
        return self.public(request, urlsplit(url).path)

    def api(self, request: httpx.Request, path: str, q: dict[str, list[str]]) -> httpx.Response:
        self.auth_headers.append(request.headers.get("Authorization"))
        parts = path.strip("/").split("/")
        echo = f"got Authorization: {request.headers.get('Authorization')}"
        if "echo_auth" in self.breaks and parts == ["pages"]:
            return J(401, {"error": "unauthorized", "message": echo})
        guarded = parts == ["store"] if "auth_only_store" in self.breaks else True
        open_preview = "preview_open" in self.breaks and parts[-1:] == ["preview"]
        authed = request.headers.get("Authorization") == f"Bearer {KEY}"
        if guarded and not open_preview and not authed and "no_401" not in self.breaks:
            return J(401, {"error": "unauthorized", "message": echo if "echo_auth" in self.breaks else "bad key"})
        m = request.method
        body = json.loads(request.content) if request.content else None
        if parts == ["store"]:
            return J(200, self.store())
        if parts == ["products"]:
            return self.list_products(q)
        if parts == ["orders"]:
            return self.list_orders(q)
        if parts[0] == "products" and len(parts) >= 2:
            product = next((p for p in self.products if str(p["id"]) == parts[1]), None)
            if product is None and "no_404" not in self.breaks:
                return J(404, {"error": "not_found"})
            if len(parts) == 2:
                p = self.product_view(product or self.products[0])
                if "get_mismatch" in self.breaks:
                    p["title"] += " (changed)"
                return J(200, p)
            if parts[2] == "reviews":
                return self.reviews(product)
            if parts[2] == "content":
                return self.put_content(m, str((product or self.products[0])["id"]), body)
        if parts == ["pages"]:
            kind = "blog" if "bad_page_kind" in self.breaks else "shipping"
            page = {
                "id": 1,
                "kind": kind,
                "title": "Shipping",
                "url": f"{BASE}/pages/shipping",
                "body_html": "<p>Ships fast.</p>",
                "updated_at": "2026-09-01T00:00:00Z",
            }
            return J(200, {"items": [page], "next_cursor": None})
        if parts[0] == "articles":
            return self.articles_api(m, parts[1:], q, body, request)
        return J(404, {"error": "not_found"})

    def store(self) -> dict:
        caps = self.caps + (["content_pull"] if "both_content" in self.breaks else [])
        store = {
            "store_id": STORE_ID,
            "name": "Example",
            "primary_host": "staging.example.com",
            "hosts": ["staging.example.com"],
            "currency": "USD",
            "capabilities": caps,
        }
        if "bad_store_schema" in self.breaks:
            del store["currency"]
        return store

    def list_products(self, q: dict[str, list[str]]) -> httpx.Response:
        limit = int(q.get("limit", ["250"])[0])
        offset = 0 if "dup_pages" in self.breaks else int(q.get("cursor", ["0"])[0])
        items = self.products
        if "unstable_ids" in self.breaks and not self.unstable_done:  # only the first read is reordered
            self.unstable_done = True
            items = list(reversed(items))
        since = q.get("updated_since", [""])[0]
        if since and "updated_since_empty" in self.breaks:
            items = []
        if since > "2100" and "ignore_updated_since" not in self.breaks:
            items = []
        page = items[offset : offset + limit]
        more = offset + limit < len(items) and "no_cursor" not in self.breaks
        return J(
            200, {"items": [self.product_view(p) for p in page], "next_cursor": str(offset + limit) if more else None}
        )

    def reviews(self, product: dict | None) -> httpx.Response:
        count = 0 if "no_reviews" in self.breaks else (product or {}).get("rating", {}).get("count", 0)
        author = "jane@example.com" if "review_email" in self.breaks else "Jane D."
        items = [
            {
                "id": f"r{i}",
                "rating": 5,
                "body": "Great",
                "author_display_name": author,
                "created_at": "2026-08-01T00:00:00Z",
            }
            for i in range(count)
        ]
        summary = {"average": 4.5, "count": 1 if "review_count_low" in self.breaks else count}
        return J(200, {"summary": summary, "items": items, "next_cursor": None})

    def put_content(self, method: str, pid: str, body: dict | None) -> httpx.Response:
        if method == "PUT":
            if "push_ignored" not in self.breaks:
                self.content[pid] = body or {}
            return httpx.Response(204)
        if "push_not_removed" not in self.breaks:
            self.content.pop(pid, None)
        return httpx.Response(204)

    # -- articles ----------------------------------------------------------------------------
    def articles_api(self, m: str, rest: list[str], q: dict, body: dict | None, request: httpx.Request):
        if not rest:
            if m == "POST":
                resp = self.create_article(body or {})
                if "create_timeout" in self.breaks:  # the article exists but the response is lost
                    raise httpx.ReadTimeout("timed out", request=request)
                return resp
            ignore_tag = "tag_filter_ignored" in self.breaks
            items = [
                a
                for a in self.articles.values()
                if (ignore_tag or not q.get("tag") or q["tag"][0] in a["tags"])
                and q.get("status", ["all"])[0] in ("all", a["status"])
            ]
            return J(200, {"items": items, "next_cursor": None})
        art = self.articles.get(rest[0])
        if art is None:
            return J(404, {"error": "not_found"})
        if rest[1:] == ["preview"]:
            if "preview_no_auth" in self.breaks:
                return J(401, {"error": "unauthorized"})
            return H(200, f"<html><body><h1>{html.escape(art['title'])}</h1>{art['body_html']}</body></html>")
        if m == "GET":
            return J(200, art)
        if m == "DELETE":
            if "delete_noop" not in self.breaks:
                del self.articles[rest[0]]
            return httpx.Response(204)
        if m == "PATCH":
            for field, value in (body or {}).items():
                art[field] = value
            if "body_html" in (body or {}) and "digest_static" not in self.breaks:
                art["content_digest"] = digest(art["body_html"])
            if (body or {}).get("status") == "published":
                art["published_at"] = art.get("published_at") or now()
                self.ever_published.add(art["id"])
                if "digest_on_publish" in self.breaks:
                    art["content_digest"] = digest(art["body_html"] + "x")
            art["updated_at"] = now()
            return J(200, art)
        return J(405, {"error": "method_not_allowed"})

    def create_article(self, body: dict) -> httpx.Response:
        if "create_500" in self.breaks:
            return J(500, {"error": "boom"})
        aid = f"art-{len(self.articles)}"
        slug = body.get("slug") or aid
        art = {
            "id": aid,
            "type": body["type"],
            "title": body["title"],
            "slug": slug,
            "url": f"{BASE}/blogs/news/{slug}",
            "preview_url": f"{API}/articles/{aid}/preview",
            "body_html": body["body_html"],
            "tags": body.get("tags", []),
            "status": "published" if "create_published" in self.breaks else "hidden",
            "published_at": None,
            "created_at": now(),
            "updated_at": now(),
            "content_digest": digest(body["body_html"]),
        }
        self.articles[aid] = art
        return J(201, art)

    def article_public(self, art: dict) -> bool:
        if "mervia-conformance" not in art["tags"]:
            return art["status"] == "published"
        if "publish_not_public" in self.breaks:
            return False
        if "hidden_public" in self.breaks:
            return True
        if "unpublish_stays_public" in self.breaks and art["id"] in self.ever_published:
            return True
        return art["status"] == "published"

    # -- storefront --------------------------------------------------------------------------
    def tag(self) -> str:
        if "no_tag" in self.breaks:
            return ""
        store = "someone-else" if "wrong_store" in self.breaks else STORE_ID
        tag = f'<script async data-store="{store}" src="{TAG_SRC}"></script>'
        return f"<!-- {tag} -->" if "tag_commented" in self.breaks else tag

    def shell(self, title: str, head: str = "", body: str = "") -> str:
        gsv = "" if "no_gsv" in self.breaks else '<meta name="google-site-verification" content="abc123">'
        return (
            f"<!doctype html><html><head><title>{html.escape(title)}</title>{gsv}{self.tag()}{head}</head>"
            f"<body><h1>{html.escape(title)}</h1>{body}</body></html>"
        )

    def public(self, request: httpx.Request, path: str) -> httpx.Response:
        if "basic_auth_site" in self.breaks:
            want = "Basic " + base64.b64encode(":".join(PUBLIC_AUTH).encode()).decode()
            if request.headers.get("Authorization") != want:
                return H(401, "authentication required")
        if path in ("", "/"):
            return H(200, self.shell("Example store"))
        if path.startswith("/products/"):
            product = next((p for p in self.products if p["url"].endswith(path)), None)
            return H(404, "not found") if product is None else self.product_page(product)
        if path.startswith("/blogs/news/"):
            art = next((a for a in self.articles.values() if a["url"].endswith(path)), None)
            if art is None or not self.article_public(art):
                return H(404, self.shell("Not found"))
            return H(200, self.shell(art["title"], body=art["body_html"]))
        if path == "/sitemap.xml":
            children = "".join(f"<sitemap><loc>{BASE}/sitemap-{k}.xml</loc></sitemap>" for k in ("products", "blogs"))
            return httpx.Response(200, text=f'<?xml version="1.0"?><sitemapindex>{children}</sitemapindex>')
        if path == "/sitemap-products.xml":
            return self.sitemap(p["url"] for p in self.products)
        if path == "/sitemap-blogs.xml":
            if "broken_child_sitemap" in self.breaks:
                return H(500, "oops")
            if "stale_sitemap" in self.breaks:
                return self.sitemap([])
            shown = [
                a["url"] for a in self.articles.values() if self.article_public(a) or "hidden_in_sitemap" in self.breaks
            ]
            return self.sitemap(shown)
        return H(404, "not found")

    def sitemap(self, urls: Any) -> httpx.Response:
        locs = "".join(f"<url><loc>{html.escape(u)}</loc></url>" for u in urls)
        return httpx.Response(200, text=f'<?xml version="1.0"?><urlset>{locs}</urlset>')

    def product_page(self, product: dict) -> httpx.Response:
        pid = str(product["id"])
        title = product["title"] if "page_no_title" not in self.breaks else "Something else"
        doc = self.content.get(pid)
        if "content_pull" in self.caps and "pull_cached" in self.breaks:  # a copy from before this run
            doc = {
                "head_html": '<script type="application/ld+json" id="mervia-product-schema">{}</script>',
                "body_html": '<section id="mervia-shopping-guide">an earlier copy</section>',
            }
        elif "content_pull" in self.caps and self.include_url:
            if self.fetch_include(product) == "fail":
                return H(500, "include failed")
            doc = self.include_last_good.get(pid)
        if not doc:
            return H(200, self.shell(title))
        if "pull_client_side" in self.breaks:
            return H(200, self.shell(title, body='<script src="https://app.mervia.ai/include.js"></script>'))
        if "push_in_body" in self.breaks:
            return H(200, self.shell(title, body=doc["head_html"] + doc["body_html"]))
        head, body = doc["head_html"], doc["body_html"]
        if "push_rewrites" in self.breaks:  # re-serialised JSON: same meaning, not "printed unchanged"
            head = head.replace('"@type":"Product"', '"@type": "Product"')
        if "pull_key_in_html" in self.breaks:
            body += f'<script>window.includeKey = "{INCLUDE_KEY}";</script>'
        return H(200, self.shell(title, head=head, body=body))

    def fetch_include(self, product: dict) -> str:
        """Fetch with a 1-second timeout; keep the last good copy on any error."""
        pid = str(product["id"])
        if self.include_cache and pid in self.include_outcomes:
            return self.include_outcomes[pid]
        outcome = self._fetch_include(product)
        self.include_outcomes[pid] = outcome
        return outcome

    def _fetch_include(self, product: dict) -> str:
        pid = str(product["id"])
        path_id = product["handle"] if "pull_internal_id" in self.breaks else pid
        headers = {} if "pull_no_bearer" in self.breaks else {"Authorization": f"Bearer {INCLUDE_KEY}"}
        timeout = 30.0 if "pull_no_timeout" in self.breaks else 1.0
        try:
            resp = httpx.get(f"{self.include_url}{STORE_ID}/products/{path_id}", headers=headers, timeout=timeout)
        except httpx.HTTPError:
            return "fail" if "pull_no_last_good" in self.breaks else "kept"
        if resp.status_code == 200:
            self.include_last_good[pid] = resp.json()
            return "ok"
        if resp.status_code == 404:
            self.include_last_good.pop(pid, None)
            return "none"
        return "fail" if "pull_no_last_good" in self.breaks else "kept"
