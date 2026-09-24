"""A local receiver for the store's signed webhooks (item 8 order events, item 11 product events).

It verifies `X-Mervia-Signature` (sha256=<hex HMAC-SHA256 of `<timestamp>.<raw body>`, the
timestamp being the exact value of `X-Mervia-Timestamp`) and `X-Mervia-Timestamp` (unix seconds,
within 300 s), records every delivery, and answers 200 when both hold and the body is JSON; 401
on a bad signature or timestamp, 400 on a non-JSON body. A signature over the body alone (the
form before contract 1.0.0-draft.2) is recognised and named, so the failure message says what to
change. The shared secret is never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..listen import BackgroundServer, QuietHandler

TOLERANCE_SECONDS = 300


def signature(secret: str, body: bytes, timestamp: str) -> str:
    """sha256=<hex HMAC-SHA256(secret, timestamp + "." + body)>: the timestamp is signed, so the window holds."""
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def body_only_signature(secret: str, body: bytes) -> str:
    """The pre-draft.2 form, recognised only to name it in a failure."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@dataclass
class Delivery:
    raw: bytes
    headers: dict[str, str]
    payload: Any
    signature_ok: bool
    timestamp_ok: bool
    timestamp_detail: str
    signature_detail: str
    status: int
    received_at: float = field(default_factory=time.time)

    @property
    def event(self) -> str:
        return str(self.payload.get("event", "")) if isinstance(self.payload, dict) else ""


class WebhookReceiver(BackgroundServer):
    def __init__(self, listen: str, secret: str, *, clock: Callable[[], float] = time.time) -> None:
        super().__init__(listen, _Handler)
        self._secret = secret
        self.clock = clock
        self.deliveries: list[Delivery] = []
        self._cond = threading.Condition()

    def inspect(self, raw: bytes, headers: dict[str, str]) -> Delivery:
        sent = headers.get("x-mervia-signature", "").encode("latin-1", "replace")
        ts_raw = headers.get("x-mervia-timestamp", "")
        sig_ok = bool(sent) and hmac.compare_digest(sent, signature(self._secret, raw, ts_raw).encode())
        if sig_ok:
            sig_detail = ""
        elif not sent:
            sig_detail = "X-Mervia-Signature is missing"
        elif hmac.compare_digest(sent, body_only_signature(self._secret, raw).encode()):
            sig_detail = (
                "X-Mervia-Signature covers the body only; since contract 1.0.0-draft.2 the HMAC input is "
                "the X-Mervia-Timestamp value, a '.', then the raw body (timestamp.body)"
            )
        else:
            sig_detail = (
                "X-Mervia-Signature is not sha256=<hex HMAC-SHA256 of timestamp.body> with the shared secret "
                "(the X-Mervia-Timestamp value, a '.', then the raw body, signed as the exact bytes sent)"
            )
        try:
            skew = abs(self.clock() - int(ts_raw))
            ts_ok, ts_detail = skew <= TOLERANCE_SECONDS, f"{skew:.0f}s from this machine's clock"
        except ValueError:
            ts_ok, ts_detail = False, f"X-Mervia-Timestamp is {ts_raw!r}, not unix seconds"
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = None
        status = 400 if payload is None else 200 if sig_ok and ts_ok else 401
        return Delivery(raw, headers, payload, sig_ok, ts_ok, ts_detail, sig_detail, status)

    def record(self, delivery: Delivery) -> None:
        with self._cond:
            self.deliveries.append(delivery)
            self._cond.notify_all()

    def wait_for(self, predicate: Callable[[Delivery], bool], timeout: float) -> Delivery | None:
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                found = next((d for d in self.deliveries if predicate(d)), None)
                remaining = deadline - time.monotonic()
                if found or remaining <= 0:
                    return found
                self._cond.wait(remaining)


MAX_BODY = 262_144  # Mervia refuses a larger body before checking the signature (contract README)


class _Handler(QuietHandler):
    def _body(self) -> bytes | str:
        """The raw body, Content-Length or chunked; a str is the reason it cannot be read."""
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            chunks: list[bytes] = []
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                        pass  # trailers
                    return b"".join(chunks)
                if sum(map(len, chunks)) + size > MAX_BODY:
                    return "body too large"
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
        length = self.headers.get("Content-Length")
        if length is None:
            return "send Content-Length or Transfer-Encoding: chunked"
        if not length.isdigit():
            return "bad Content-Length"
        if int(length) > MAX_BODY:
            return "body too large"
        return self.rfile.read(int(length))

    def _answer(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        receiver: WebhookReceiver = self.server.owner  # type: ignore[attr-defined]
        try:
            raw = self._body()
        except ValueError:
            raw = "malformed chunked body"
        if isinstance(raw, str):
            status = 411 if "Content-Length" in raw else 413 if "too large" in raw else 400
            self._answer(status, json.dumps({"error": raw}).encode())
            return
        try:
            delivery = receiver.inspect(raw, {k.lower(): v for k, v in self.headers.items()})
        except Exception:  # noqa: BLE001 - a malformed delivery must never kill the handler thread
            self._answer(400, b'{"error":"unreadable delivery"}')
            return
        receiver.record(delivery)
        self._answer(delivery.status, b'{"ok":true}' if delivery.status == 200 else b'{"error":"rejected"}')

    def do_GET(self) -> None:  # noqa: N802
        body = b"mervia-check webhook receiver: POST signed webhooks here\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
