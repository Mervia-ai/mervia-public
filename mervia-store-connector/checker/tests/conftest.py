from __future__ import annotations

import socket

import pytest
from fakestore import API, KEY, FakeStore

from mervia_check.checks import Options
from mervia_check.report import Result
from mervia_check.runner import run


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Run:
    def __init__(self, results: list[Result], messages: list[str]):
        self.results = results
        self.messages = messages

    def status(self, name: str) -> str:
        found = [r for r in self.results if r.name == name]
        assert found, f"no result named {name}; have {[r.name for r in self.results]}"
        return found[0].status

    def get(self, name: str) -> Result:
        return next(r for r in self.results if r.name == name)

    def failures(self) -> list[str]:
        return [f"{r.name}: {r.detail}" for r in self.results if r.status == "fail"]


@pytest.fixture
def check():
    """check(store, items=[...], **option overrides) -> Run."""

    def _check(store: FakeStore, items: list[int] | None = None, **overrides) -> Run:
        overrides.setdefault("allow_writes", True)  # the CLI's default (False) is tested in test_cli
        overrides.setdefault("base_url", API)
        opts = Options(api_key=KEY, items=items, **overrides)
        messages: list[str] = []
        results, _ = run(opts, transport=store.transport(), sleep=lambda _s: None, say=messages.append, rate=0)
        return Run(results, messages)

    return _check
