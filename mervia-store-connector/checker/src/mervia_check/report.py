"""Results and the two report renderers (text, JSON)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

import httpx

from .client import exchange

Status = Literal["pass", "fail", "skip"]
WARNING = "warning: "

ITEM_NAMES: dict[int, str] = {
    1: "Store identity endpoint GET /store",
    2: "Products endpoint GET /products, GET /products/{id}",
    3: "Reviews endpoint GET /products/{id}/reviews",
    4: "Pages endpoint GET /pages (optional)",
    5: "Articles API /articles",
    6: "Product-page content PUT/DELETE /products/{id}/content",
    7: "Tracking tag",
    8: "Orders endpoint GET /orders",
    9: "Search Console tag",
    10: "Chat widget tag (later)",
    11: "Product-changed webhook (by arrangement)",
}
ITEM_ORDER = list(ITEM_NAMES)


@dataclass
class Result:
    item: int
    name: str
    status: Status
    detail: str = ""
    request: dict[str, Any] | None = None
    response: dict[str, Any] | None = None

    @property
    def warning(self) -> bool:
        return self.status == "pass" and self.detail.startswith(WARNING)


Source = httpx.Response | httpx.HTTPError | None


def ok(item: int, name: str, detail: str = "") -> Result:
    return Result(item, name, "pass", detail)


def warn(item: int, name: str, detail: str, source: Source = None) -> Result:
    """A pass the merchant should still look at (a blocked fetch, a cached sitemap)."""
    request, response = exchange(source)
    return Result(item, name, "pass", WARNING + detail, request, response)


def fail(item: int, name: str, detail: str, source: Source = None) -> Result:
    request, response = exchange(source)
    return Result(item, name, "fail", detail, request, response)


def skip(item: int, name: str, detail: str) -> Result:
    return Result(item, name, "skip", detail)


def check(item: int, name: str, condition: bool, detail: str, source: Source = None, ok_detail: str = "") -> Result:
    """pass when `condition`, else fail with `detail` and the exchange."""
    return ok(item, name, ok_detail) if condition else fail(item, name, detail, source)


GO_LIVE_ITEMS = (1, 2, 3, 5, 6, 7, 8)  # item 4 is optional; 9 is placed by Mervia later; 10 comes later


def go_live_missing(results: list[Result]) -> list[int]:
    """Go-live items with no result other than a skip: not checked in this run."""
    return [i for i in GO_LIVE_ITEMS if not any(r.item == i and r.status != "skip" for r in results)]


def go_live_line(results: list[Result]) -> str:
    missing = go_live_missing(results)
    if not missing:
        return "GO-LIVE: COMPLETE (items 1, 2, 3, 5, 6, 7, 8 checked)"
    return f"GO-LIVE: INCOMPLETE ({', '.join(map(str, missing))} not checked)"


def summary(results: list[Result]) -> dict[str, int]:
    return {
        "pass": sum(r.status == "pass" for r in results),
        "warn": sum(r.warning for r in results),
        "fail": sum(r.status == "fail" for r in results),
        "skip": sum(r.status == "skip" for r in results),
    }


def exit_code(results: list[Result]) -> int:
    return 1 if any(r.status == "fail" for r in results) else 0


def _ordered(results: list[Result]) -> list[Result]:
    rank = {item: i for i, item in enumerate(ITEM_ORDER)}
    return sorted(results, key=lambda r: rank.get(r.item, 99))


def render_json(results: list[Result], meta: dict[str, Any]) -> str:
    missing = go_live_missing(results)
    payload = {
        **meta,
        "summary": summary(results),
        "go_live": {"complete": not missing, "not_checked": missing},
        "results": [asdict(r) for r in _ordered(results)],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _indent(text: str, prefix: str) -> str:
    return "\n".join(prefix + line for line in text.splitlines() or [""])


def render_text(results: list[Result], meta: dict[str, Any]) -> str:
    lines = [
        f"Mervia Store Connector conformance (contract {meta.get('contract_version', '?')})",
        f"base URL: {meta.get('base_url', '')}",
        f"run: {meta.get('run_id', '')}",
    ]
    current: int | None = None
    for r in _ordered(results):
        if r.item != current:
            current = r.item
            lines += ["", f"Item {r.item}  {ITEM_NAMES.get(r.item, '')}"]
        label = "WARN" if r.warning else r.status.upper()
        detail = r.detail[len(WARNING) :] if r.warning else r.detail
        lines.append(f"  {label:<4}  {r.name}" + (f"  {detail}" if detail else ""))
        if r.request:
            lines.append(f"        request:  {r.request['method']} {r.request['url']}")
            for k, v in r.request["headers"].items():
                lines.append(f"                  {k}: {v}")
            if r.request["body"]:
                lines.append(_indent(r.request["body"], "                  "))
        if r.response:
            lines.append(f"        response: {r.response['status']}")
            for k, v in r.response["headers"].items():
                lines.append(f"                  {k}: {v}")
            if r.response["body"]:
                lines.append(_indent(r.response["body"], "                  "))
    s = summary(results)
    lines += [
        "",
        f"{s['pass']} passed ({s['warn']} with warnings), {s['fail']} failed, {s['skip']} skipped",
        "RESULT: " + ("FAIL" if s["fail"] else "PASS"),
        go_live_line(results),
    ]
    return "\n".join(lines) + "\n"
