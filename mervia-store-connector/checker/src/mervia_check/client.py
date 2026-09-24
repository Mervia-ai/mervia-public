"""HTTP client for the store's API and public pages.

- Every API request carries `Authorization: Bearer <key>`; public-page requests carry none.
- Requests are throttled to stay under the contract's 2 requests per second.
- A 429 is retried after its Retry-After (capped), up to `max_retries` times.
- `Authorization` headers never appear in anything this module records: `exchange()` masks them.
  Everything else is scrubbed by `redact.Redactor` before it leaves the checker.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

BODY_LIMIT = 2000
RETRY_AFTER_CAP = 60.0
USER_AGENT = "mervia-check/0.1 (+https://mervia.ai)"


class Client:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 10.0,
        verify: bool = True,
        rate: float = 2.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        public_auth: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._key = api_key
        self._interval = 1.0 / rate if rate > 0 else 0.0
        self._max_retries = max_retries
        self._sleep = sleep
        user, _, password = (public_auth or "").partition(":")
        self._public_auth = httpx.BasicAuth(user, password) if public_auth else None
        self._lock = threading.Lock()
        self._last_sent = 0.0
        self._http = httpx.Client(
            timeout=timeout,
            verify=verify,
            transport=transport,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        )

    @property
    def key(self) -> str:
        return self._key

    def close(self) -> None:
        self._http.close()

    def _throttle(self) -> None:
        if not self._interval:
            return
        with self._lock:
            wait = self._last_sent + self._interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_sent = time.monotonic()

    def _send(self, request: httpx.Request) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            self._throttle()
            response = self._http.send(request)
            response.read()
            if response.status_code != 429 or attempt == self._max_retries:
                return response
            self._sleep(_retry_after(response))
        raise AssertionError("unreachable")

    def api(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        key: str | None = None,
        auth: bool = True,
    ) -> httpx.Response:
        """Call an endpoint relative to the base URL. `key` replaces the API key (401 probes)."""
        headers = {"Accept": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self._key if key is None else key}"
        request = self._http.build_request(method, self.base_url + path, params=params, json=json, headers=headers)
        return self._send(request)

    def fetch(self, url: str, *, auth: bool = False) -> httpx.Response:
        """GET an absolute URL (public page, sitemap, preview). No redirects are followed.

        With `auth` the API key is sent as a Bearer token; otherwise the `--public-auth`
        Basic credentials, if any, which staging sites behind HTTP basic auth need.
        """
        headers = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
        if auth:
            headers["Authorization"] = f"Bearer {self._key}"
        request = self._http.build_request("GET", url, headers=headers)
        if not auth and self._public_auth is not None:
            request = next(self._public_auth.auth_flow(request))
        return self._send(request)


def _retry_after(response: httpx.Response) -> float:
    raw = response.headers.get("Retry-After", "1").strip()
    try:
        seconds = float(raw)
    except ValueError:
        try:  # the HTTP-date form, e.g. "Wed, 21 Oct 2026 07:28:00 GMT"
            seconds = (parsedate_to_datetime(raw) - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError):
            seconds = 1.0
    return max(0.0, min(seconds, RETRY_AFTER_CAP))


def _clip(text: str) -> str:
    if len(text) <= BODY_LIMIT:
        return text
    return text[:BODY_LIMIT] + f"... [{len(text) - BODY_LIMIT} more characters]"


def describe_request(request: httpx.Request) -> dict[str, Any]:
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("user-agent", "accept-encoding")}
    for name in list(headers):
        if name.lower() == "authorization":
            headers[name] = headers[name].split(" ", 1)[0] + " ***"
    body = request.content.decode("utf-8", "replace") if request.content else ""
    return {"method": request.method, "url": str(request.url), "headers": headers, "body": _clip(body)}


def describe_response(response: httpx.Response) -> dict[str, Any]:
    keep = ("content-type", "location", "retry-after", "cache-control")
    headers = {k: v for k, v in response.headers.items() if k.lower() in keep}
    return {"status": response.status_code, "headers": headers, "body": _clip(response.text)}


def exchange(
    source: httpx.Response | httpx.HTTPError | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The (request, response) pair to attach to a Result, key redacted."""
    if source is None:
        return None, None
    if isinstance(source, httpx.Response):
        return describe_request(source.request), describe_response(source)
    try:
        return describe_request(source.request), None
    except RuntimeError:
        return None, None
