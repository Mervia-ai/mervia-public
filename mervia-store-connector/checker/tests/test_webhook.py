from __future__ import annotations

import json
import socket
import threading
import time

import httpx
import pytest
from conftest import free_port
from fakestore import API, KEY, STORE_ID, WEBHOOK_CAPS, FakeStore

from mervia_check.checks import Options
from mervia_check.receiver.webhook_receiver import WebhookReceiver, body_only_signature, signature
from mervia_check.runner import RunError, run

SECRET = "whsec-test"


def order_event(**order_overrides) -> dict:
    order = {
        "id": 5001,
        "status": "paid",
        "updated_at": "2026-09-01T10:00:00Z",
        "refunded_total": "0.00",
        "paid_at": "2026-09-01T10:00:00Z",
        "currency": "USD",
        "total": "129.00",
        "line_items": [{"product_id": 101, "quantity": 1, "price": "129.00"}],
        "mervia_attribution": None,
    }
    order.update(order_overrides)
    return {"event_id": "evt-1", "event": "order.paid", "store_id": STORE_ID, "order": order}


def send_later(
    port: int, payload: dict | bytes, *, secret: str = SECRET, skew: int = 0, body_only: bool = False
) -> threading.Thread:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    timestamp = str(int(time.time()) + skew)
    headers = {
        "Content-Type": "application/json",
        "X-Mervia-Signature": body_only_signature(secret, raw) if body_only else signature(secret, raw, timestamp),
        "X-Mervia-Timestamp": timestamp,
    }

    def post() -> None:
        for _ in range(100):
            try:
                httpx.post(f"http://127.0.0.1:{port}/", content=raw, headers=headers)
                return
            except httpx.ConnectError:
                time.sleep(0.05)

    thread = threading.Thread(target=post, daemon=True)
    thread.start()
    return thread


def _run(check, *payloads, items=(1, 8), **send):
    port = free_port()
    for p in payloads:
        send_later(port, p, **send)
    return check(
        FakeStore(caps=WEBHOOK_CAPS),
        items=list(items) if items else None,
        webhook_secret=SECRET,
        webhook_listen=f"127.0.0.1:{port}",
        webhook_timeout=5,
    )


def test_signed_order_event_passes(check):
    run_ = _run(check, order_event())
    assert run_.failures() == []
    assert run_.status("8.webhook.attribution") == "pass"
    assert not any(SECRET in m for m in run_.messages)


def test_body_only_signature_fails_and_names_the_rule(check):
    """A signature over the body alone, the form before contract 1.0.0-draft.2, is a clear failure."""
    run_ = _run(check, order_event(), body_only=True)
    assert run_.status("8.webhook.signature") == "fail"
    detail = run_.get("8.webhook.signature").detail
    assert "covers the body only" in detail and "timestamp.body" in detail
    assert run_.status("8.webhook.timestamp") == "pass"


def test_signature_binds_the_timestamp(check):
    """The same body re-sent with a fresh timestamp does not verify: the window is real."""
    raw = json.dumps(order_event()).encode()
    stale = signature(SECRET, raw, str(int(time.time()) - 3600))
    port = free_port()
    threading.Thread(
        target=lambda: httpx.post(
            f"http://127.0.0.1:{port}/",
            content=raw,
            headers={"X-Mervia-Signature": stale, "X-Mervia-Timestamp": str(int(time.time()))},
        ),
        daemon=True,
    ).start()
    run_ = check(
        FakeStore(caps=WEBHOOK_CAPS),
        items=[1, 8],
        webhook_secret=SECRET,
        webhook_listen=f"127.0.0.1:{port}",
        webhook_timeout=5,
    )
    assert run_.status("8.webhook.signature") == "fail"
    assert run_.status("8.webhook.timestamp") == "pass"


def test_wrong_secret_fails_signature(check):
    run_ = _run(check, order_event(), secret="other")
    assert run_.status("8.webhook.signature") == "fail"
    assert SECRET not in repr(run_.results)


def test_stale_timestamp_fails(check):
    assert _run(check, order_event(), skew=-3600).status("8.webhook.timestamp") == "fail"


def test_missing_attribution_fails(check):
    event = order_event()
    del event["order"]["mervia_attribution"]
    assert _run(check, event).status("8.webhook.attribution") == "fail"


def test_schema_violation_fails(check):
    assert _run(check, order_event(total=129)).status("8.webhook.schema") == "fail"


def test_no_delivery_fails(check):
    port = free_port()
    run_ = check(
        FakeStore(caps=WEBHOOK_CAPS),
        items=[8],
        webhook_secret=SECRET,
        webhook_listen=f"127.0.0.1:{port}",
        webhook_timeout=0.3,
    )
    assert run_.status("8.webhook.received") == "fail"


def test_product_event_validates_item_11(check):
    product = {"event_id": "evt-2", "event": "product.updated", "store_id": STORE_ID, "product_id": 101}
    run_ = _run(check, order_event(), product, items=(1, 8, 11))
    assert run_.status("11.webhook.schema") == "pass"
    assert run_.status("11.webhook.signature") == "pass"


def test_item_11_not_waited_for_unless_requested(check):
    started = time.monotonic()
    port = free_port()
    send_later(port, order_event())
    run_ = check(
        FakeStore(caps=WEBHOOK_CAPS),
        webhook_secret=SECRET,
        webhook_listen=f"127.0.0.1:{port}",
        webhook_timeout=30,
        allow_writes=False,
    )
    assert time.monotonic() - started < 10
    assert run_.status("8.webhook.received") == "pass"
    assert run_.status("11.webhook.received") == "skip"


def test_delivery_during_other_checks_counts(check):
    """The receiver is bound at startup, so an order placed early is not lost."""
    port = free_port()
    send_later(port, order_event()).join(timeout=1)  # fails to connect until bound; retried
    run_ = check(
        FakeStore(caps=WEBHOOK_CAPS),
        items=[1, 2, 8],
        webhook_secret=SECRET,
        webhook_listen=f"127.0.0.1:{port}",
        webhook_timeout=5,
    )
    assert run_.status("8.webhook.received") == "pass"


def test_no_secret_skips(check):
    assert check(FakeStore(caps=WEBHOOK_CAPS), items=[8]).status("8.webhook.received") == "skip"


def test_port_in_use_stops_the_run():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        opts = Options(base_url=API, api_key=KEY, items=[8], webhook_secret=SECRET, webhook_listen=f"127.0.0.1:{port}")
        with pytest.raises(RunError, match="cannot start the webhook receiver"):
            run(opts, transport=FakeStore(caps=WEBHOOK_CAPS).transport(), rate=0)


@pytest.fixture
def receiver():
    r = WebhookReceiver("127.0.0.1:0", SECRET).start()
    yield r
    r.stop()


def _headers(raw: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    return {"X-Mervia-Signature": signature(SECRET, raw, timestamp), "X-Mervia-Timestamp": timestamp}


def test_receiver_answers(receiver):
    url = f"http://{receiver.address}/"
    raw = json.dumps(order_event()).encode()
    bad = {"X-Mervia-Signature": "sha256=00", "X-Mervia-Timestamp": str(int(time.time()))}
    assert httpx.post(url, content=raw, headers=bad).status_code == 401
    assert httpx.post(url, content=raw, headers=_headers(raw)).status_code == 200
    assert httpx.post(url, content=b"not json", headers=_headers(b"not json")).status_code == 400


def test_receiver_refuses_a_body_over_256_kb(receiver):
    url = f"http://{receiver.address}/"
    big = json.dumps(order_event(number="x" * 262_144)).encode()
    assert len(big) > 262_144
    assert httpx.post(url, content=big, headers=_headers(big)).status_code == 413
    assert httpx.post(url, content=iter([big[:1000], big[1000:]]), headers=_headers(big)).status_code == 413
    just_under = json.dumps(order_event(number="x" * (262_144 - 500))).encode()
    assert len(just_under) <= 262_144
    assert httpx.post(url, content=just_under, headers=_headers(just_under)).status_code == 200
    assert receiver.deliveries[-1].raw == just_under


def test_receiver_reads_chunked_bodies(receiver):
    raw = json.dumps(order_event()).encode()
    resp = httpx.post(f"http://{receiver.address}/", content=iter([raw[:20], raw[20:]]), headers=_headers(raw))
    assert resp.status_code == 200
    assert receiver.deliveries[-1].raw == raw


def _raw_request(receiver, head: bytes) -> bytes:
    host, port = receiver.address.split(":")
    with socket.create_connection((host, int(port))) as s:
        s.sendall(head)
        return s.recv(4096)


def test_receiver_requires_a_length(receiver):
    assert b" 411 " in _raw_request(receiver, b"POST / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")


def test_receiver_survives_non_ascii_signature(receiver):
    body = b"{}"
    head = (
        b"POST / HTTP/1.1\r\nHost: x\r\nConnection: close\r\nContent-Length: 2\r\n"
        b"X-Mervia-Signature: sha256=\xc3\xa9\r\nX-Mervia-Timestamp: 1\r\n\r\n" + body
    )
    assert b" 401 " in _raw_request(receiver, head)
    raw = json.dumps(order_event()).encode()
    assert httpx.post(f"http://{receiver.address}/", content=raw, headers=_headers(raw)).status_code == 200
