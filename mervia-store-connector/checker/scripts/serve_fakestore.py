"""Serve the test fake store over real HTTPS, for an end-to-end run of the installed checker.

The unit tests drive the checker through an in-process transport, so they never open a socket.
This script puts the same fake store (tests/fakestore.py) behind a real TLS listener so that the
installed `mervia-check` command, or the Docker image, can be run against it the way a merchant
runs it against staging: real connections, timeouts, rate limiting, the webhook receiver and the
include stub reached over the network.

    python3 scripts/serve_fakestore.py --listen 0.0.0.0:8443 --public-host localhost \
        --webhook-to http://127.0.0.1:8788/ --webhook-secret whsec-test

Then, in another shell (see README, "Smoke run"):

    MERVIA_CHECK_API_KEY=test-key-123 mervia-check --base-url https://localhost:8443/api/mervia/v1 \
        --public-base-url https://localhost:8443 --store-id example-us --allow-writes --insecure \
        --webhook-secret whsec-test

A self-signed certificate is generated with openssl unless --cert and --key are given, hence
--insecure on the checker side. --content pull serves the content_pull capability and fetches the
document from --include-url (the checker's stub) instead of accepting PUT /products/{id}/content.
--webhook-to delivers one signed order.paid and one product.updated event to that URL a few seconds
after start-up, standing in for the test order a merchant places on staging.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
import fakestore  # noqa: E402


class StoreHandler(BaseHTTPRequestHandler):
    store: fakestore.FakeStore
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        sys.stderr.write("fakestore: " + (format % args) + "\n")

    def _serve(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        request = httpx.Request(
            self.command, fakestore.BASE + self.path, headers=dict(self.headers.items()), content=body
        )
        try:
            response = self.store.handle(request)
        except httpx.HTTPError:  # a deliberate "lost response" break: drop the connection
            self.close_connection = True
            return
        content = response.content
        self.send_response(response.status_code)
        for name, value in response.headers.items():
            if name.lower() not in ("content-length", "transfer-encoding"):
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve


def self_signed(hosts: list[str], directory: Path) -> tuple[Path, Path]:
    cert, key = directory / "cert.pem", directory / "key.pem"
    names = ",".join(f"IP:{h}" if h.replace(".", "").isdigit() else f"DNS:{h}" for h in hosts)
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "2",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            f"/CN={hosts[0]}",
            "-addext",
            f"subjectAltName={names}",
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


def send_webhooks(url: str, secret: str, delay: float) -> None:
    """Deliver a signed order.paid and product.updated event, like a store after a test order."""
    time.sleep(delay)
    order = {
        "id": 5001,
        "status": "paid",
        "updated_at": "2026-09-01T10:00:00Z",
        "refunded_total": "0.00",
        "paid_at": fakestore.now(),
        "currency": "USD",
        "total": "129.00",
        "line_items": [{"product_id": 101, "quantity": 1, "price": "129.00"}],
        "mervia_attribution": None,
    }
    events = [
        {"event_id": "evt-order-1", "event": "order.paid", "store_id": fakestore.STORE_ID, "order": order},
        {"event_id": "evt-product-1", "event": "product.updated", "store_id": fakestore.STORE_ID, "product_id": 101},
    ]
    for event in events:
        raw = json.dumps(event).encode()
        timestamp = str(int(time.time()))
        signed = timestamp.encode() + b"." + raw  # the contract signs timestamp.body
        headers = {
            "Content-Type": "application/json",
            "X-Mervia-Signature": "sha256=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest(),
            "X-Mervia-Timestamp": timestamp,
        }
        for attempt in range(60):
            try:
                response = httpx.post(url, content=raw, headers=headers, timeout=5)
                sys.stderr.write(f"fakestore: webhook {event['event']} -> {url} answered {response.status_code}\n")
                break
            except httpx.HTTPError as exc:
                if attempt == 59:
                    sys.stderr.write(f"fakestore: webhook {event['event']} could not be delivered: {exc}\n")
                time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--listen", default="0.0.0.0:8443", help="HOST:PORT to bind (default 0.0.0.0:8443)")
    parser.add_argument(
        "--public-host",
        default="localhost",
        help="host name the checker uses to reach this store; it is what the store's URLs carry",
    )
    parser.add_argument("--content", choices=["push", "pull"], default="push", help="which item 6 option to serve")
    parser.add_argument(
        "--include-url", help="for --content pull: the checker's include stub, e.g. http://127.0.0.1:8787/include/v1/"
    )
    parser.add_argument(
        "--breaks", default="", help="comma-separated fake-store defects to switch on (see tests/fakestore.py)"
    )
    parser.add_argument(
        "--include-cache",
        action="store_true",
        help="for --content pull: cache each product's include outcome for the run (the contract's 15-minute cache)",
    )
    parser.add_argument("--cert", type=Path)
    parser.add_argument("--key", type=Path)
    parser.add_argument(
        "--webhooks",
        action="store_true",
        help="declare order_webhook and product_webhook too (the by-arrangement webhooks; needs --webhook-to)",
    )
    parser.add_argument("--webhook-to", help="deliver a signed order and product event to this URL after start-up")
    parser.add_argument("--webhook-secret", default="whsec-test")
    parser.add_argument("--webhook-after", type=float, default=8.0, help="seconds to wait before delivering")
    args = parser.parse_args()

    host, _, port = args.listen.rpartition(":")
    fakestore.BASE = f"https://{args.public_host}:{port}"
    fakestore.API = fakestore.BASE + "/api/mervia/v1"
    caps = [c for c in fakestore.DEFAULT_CAPS if c != "content_push"]
    caps.append("content_pull" if args.content == "pull" else "content_push")
    if args.webhooks or args.webhook_to:
        caps += ["order_webhook", "product_webhook"]
    if args.content == "pull" and not args.include_url:
        parser.error("--content pull needs --include-url")
    breaks = tuple(b for b in args.breaks.split(",") if b)
    StoreHandler.store = fakestore.FakeStore(
        caps=caps, breaks=breaks, include_url=args.include_url, include_cache=args.include_cache
    )

    if args.cert and args.key:
        cert, key = args.cert, args.key
    else:
        cert, key = self_signed(
            [args.public_host, "localhost", "host.docker.internal", "127.0.0.1"],
            Path(tempfile.mkdtemp(prefix="fakestore-")),
        )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))

    server = ThreadingHTTPServer((host or "0.0.0.0", int(port)), StoreHandler)
    server.daemon_threads = True
    server.socket = context.wrap_socket(server.socket, server_side=True)
    if args.webhook_to:
        threading.Thread(
            target=send_webhooks, args=(args.webhook_to, args.webhook_secret, args.webhook_after), daemon=True
        ).start()
    sys.stderr.write(
        f"fakestore: serving {fakestore.API} (public {fakestore.BASE}), capabilities {caps}, "
        f"api key {fakestore.KEY!r}, store id {fakestore.STORE_ID!r}\n"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
