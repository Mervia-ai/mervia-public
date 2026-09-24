"""A stand-in for Mervia's product-page include endpoint (item 6, pull alternative by arrangement).

It answers GET /include/v1/<store key>/products/<product id> with one include document
(`schemas/include-response.schema.json`) carrying a run-unique token, for the product ids the
checker expects, in one of four modes the checker switches between:

- ok:       200 with the document, an ETag and Cache-Control; 304 on a matching If-None-Match
- slow:     the same, after sleeping `slow_seconds` (the store must time out)
- error:    500
- notfound: 404 (nothing live for the product)

Any other path, or a product id the checker did not expect, answers 404, as real Mervia would.
The Bearer value is handed to `on_bearer` (the checker's redactor) and kept only to look for it
in page HTML; it is never recorded in a request log or a result.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit

from ..listen import BackgroundServer, QuietHandler

MODES = ("ok", "slow", "error", "notfound")
PATH = re.compile(r"^/include/v1/([^/]+)/products/([^/]+)$")


def document(version: int, token: str) -> dict[str, Any]:
    """The conformance document: the two ids Mervia uses, and a token that proves freshness."""
    head = (
        '<script type="application/ld+json" id="mervia-product-schema">'
        f'{{"@context":"https://schema.org","@type":"Product","name":"mervia-conformance {token}"}}</script>'
    )
    body = f'<section id="mervia-shopping-guide" data-mervia-conformance="{token}">mervia-conformance {token}</section>'
    return {"version": version, "head_html": head, "body_html": body}


@dataclass
class StubRequest:
    path: str
    product_id: str | None  # None when the path does not match the include path
    bearer: bool
    mode: str
    at: float


class IncludeStub(BackgroundServer):
    def __init__(
        self,
        listen: str,
        *,
        slow_seconds: float = 8.0,
        version: int = 1,
        token: str = "stub",
        on_bearer: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(listen, _Handler)
        self.mode = "ok"
        self.slow_seconds = slow_seconds
        self.document = document(version, token)
        self.etag = f'"{version}"'
        self.expected: set[str] | None = None  # product ids to serve; None serves any
        self.requests: list[StubRequest] = []
        self._bearers: set[str] = set()
        self._on_bearer = on_bearer
        self._lock = threading.Lock()

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.mode = mode

    def expect(self, product_ids: set[str]) -> None:
        self.expected = set(product_ids)

    def record(self, path: str, bearer: str | None) -> tuple[str, str | None]:
        match = PATH.match(urlsplit(path).path)
        pid = unquote(match.group(2)) if match else None
        with self._lock:
            if bearer:
                self._bearers.add(bearer)
                if self._on_bearer:
                    self._on_bearer(bearer)
            self.requests.append(StubRequest(path, pid, bool(bearer), self.mode, time.time()))
            return self.mode, pid

    def bearer_in(self, text: str) -> bool:
        """Whether any bearer the store sent appears in `text` (the include key must stay server-side)."""
        with self._lock:
            return any(b in text for b in self._bearers)

    def count(self, product_id: str | None = None) -> int:
        with self._lock:
            return sum(1 for r in self.requests if product_id is None or r.product_id == product_id)


class _Handler(QuietHandler):
    def do_GET(self) -> None:  # noqa: N802
        stub: IncludeStub = self.server.owner  # type: ignore[attr-defined]
        auth = self.headers.get("Authorization", "")
        bearer = auth[len("Bearer ") :].strip() if auth.startswith("Bearer ") else None
        mode, pid = stub.record(self.path, bearer or None)
        if pid is None or (stub.expected is not None and pid not in stub.expected):
            self._send(404, {"error": "not_found", "message": "not an include path for an expected product"})
            return
        if mode == "slow":
            time.sleep(stub.slow_seconds)
        if mode == "error":
            self._send(500, {"error": "stub_error", "message": "mervia-check include stub in error mode"})
        elif mode == "notfound":
            self._send(404, {"error": "not_found", "message": "nothing live for this product"})
        elif self.headers.get("If-None-Match") == stub.etag:
            self._send(304, None, stub.etag)
        else:
            self._send(200, stub.document, stub.etag)

    def _send(self, status: int, body: dict[str, Any] | None, etag: str | None = None) -> None:
        payload = json.dumps(body).encode() if body is not None else b""
        try:
            self.send_response(status)
            if etag:
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "private, max-age=900")
            if body is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except OSError:
            pass  # the store gave up waiting (slow mode); nothing to answer
