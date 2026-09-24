"""Small shared plumbing for the two local servers (include stub, webhook receiver)."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def parse_listen(value: str) -> tuple[str, int]:
    """'0.0.0.0:8788' -> ('0.0.0.0', 8788). Port 0 picks a free port."""
    host, sep, port = value.rpartition(":")
    if not sep or not port.isdigit():
        raise ValueError(f"expected HOST:PORT, got {value!r}")
    return host or "0.0.0.0", int(port)


class BackgroundServer:
    """A ThreadingHTTPServer on a daemon thread."""

    def __init__(self, listen: str, handler: type[BaseHTTPRequestHandler]) -> None:
        host, port = parse_listen(listen)
        self.server = ThreadingHTTPServer((host, port), handler)
        self.server.daemon_threads = True
        self.server.owner = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def address(self) -> str:
        host, port = self.server.server_address[:2]
        return f"{host}:{port}"

    def start(self) -> BackgroundServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class QuietHandler(BaseHTTPRequestHandler):
    """No per-request logging to stderr; the checker reports what matters."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return
