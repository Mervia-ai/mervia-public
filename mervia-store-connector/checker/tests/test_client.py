from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx

from mervia_check.client import Client, exchange


def test_bearer_sent_and_masked_in_exchange():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"ok": True})

    client = Client("https://x.test/api", "s3cret-key", transport=httpx.MockTransport(handler), rate=0)
    request, response = exchange(client.api("GET", "/store"))
    assert seen["auth"] == "Bearer s3cret-key"
    assert request["headers"]["authorization"] == "Bearer ***"
    assert "s3cret-key" not in str(request) + str(response)


def test_key_override_and_no_key():
    seen = []

    def handler(request):
        seen.append(request.headers.get("Authorization"))
        return httpx.Response(401)

    client = Client("https://x.test", "k", transport=httpx.MockTransport(handler), rate=0)
    client.api("GET", "/store", key="other")
    client.api("GET", "/store", auth=False)
    assert seen == ["Bearer other", None]


def test_public_fetch_sends_no_key_and_does_not_follow_redirects():
    seen = []

    def handler(request):
        seen.append(request.headers.get("Authorization"))
        return httpx.Response(301, headers={"Location": "https://x.test/other"})

    client = Client("https://x.test", "k", transport=httpx.MockTransport(handler), rate=0)
    assert client.fetch("https://x.test/page").status_code == 301
    assert seen == [None]


def test_public_auth_is_basic_and_masked():
    seen = []

    def handler(request):
        seen.append(request.headers.get("Authorization"))
        return httpx.Response(200)

    client = Client("https://x.test", "k", transport=httpx.MockTransport(handler), rate=0, public_auth="u:pw12345")
    request, _ = exchange(client.fetch("https://x.test/"))
    client.fetch("https://x.test/", auth=True)
    assert seen[0].startswith("Basic ") and seen[1] == "Bearer k"
    assert request["headers"]["authorization"] == "Basic ***"


def test_429_retry_after_is_honoured():
    calls, sleeps = [], []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={})

    client = Client("https://x.test", "k", transport=httpx.MockTransport(handler), rate=0, sleep=sleeps.append)
    assert client.api("GET", "/store").status_code == 200
    assert sleeps == [7.0, 7.0]


def test_retry_after_http_date():
    when = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    calls, sleeps = [], []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": when}) if len(calls) == 1 else httpx.Response(200)

    client = Client("https://x.test", "k", transport=httpx.MockTransport(handler), rate=0, sleep=sleeps.append)
    client.api("GET", "/store")
    assert 25 <= sleeps[0] <= 30


def test_429_gives_up_after_max_retries():
    client = Client(
        "https://x.test",
        "k",
        rate=0,
        max_retries=2,
        sleep=lambda _s: None,
        transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": "999"})),
    )
    assert client.api("GET", "/store").status_code == 429


def test_throttle_keeps_under_rate():
    client = Client("https://x.test", "k", rate=20, transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    start = time.monotonic()
    for _ in range(4):
        client.api("GET", "/store")
    assert time.monotonic() - start >= 0.14  # 3 gaps of 50 ms


def test_long_bodies_are_clipped():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text="a" * 5000))
    client = Client("https://x.test", "k", rate=0, transport=transport)
    _, response = exchange(client.fetch("https://x.test/"))
    assert len(response["body"]) < 2100 and "more characters" in response["body"]
