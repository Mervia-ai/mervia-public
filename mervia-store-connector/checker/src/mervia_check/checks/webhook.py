"""The by-arrangement webhooks: order events (item 8, `order_webhook`) and product-changed events
(item 11, `product_webhook`), received on a local server. They run only for a store that declares
those capabilities; by default Mervia reads orders from GET /orders (checks/orders.py).

The merchant sets their staging store's Mervia webhook URL to one that reaches
`--webhook-listen`, then places a test order (and edits a product, for item 11) while the
checker waits up to `--webhook-timeout` seconds.
"""

from __future__ import annotations

import time
from typing import Any

from .. import contract
from ..client import BODY_LIMIT
from ..receiver.webhook_receiver import Delivery
from ..report import Result, skip
from . import Context, sid

SCHEMAS = {8: ("order.", "order-event.schema.json"), 11: ("product.", "product-event.schema.json")}


def _exchange(d: Delivery) -> tuple[dict[str, Any], dict[str, Any]]:
    headers = {k: v for k, v in d.headers.items() if k.startswith("x-mervia") or k == "content-type"}
    body = d.raw.decode("utf-8", "replace")[:BODY_LIMIT]
    return (
        {"method": "POST", "url": "(webhook receiver)", "headers": headers, "body": body},
        {"status": d.status, "headers": {}, "body": ""},
    )


def _result(item: int, name: str, passed: bool, detail: str, d: Delivery, ok_detail: str = "") -> Result:
    if passed:
        return Result(item, name, "pass", ok_detail)
    request, response = _exchange(d)
    return Result(item, name, "fail", detail, request, response)


def _validate(ctx: Context, item: int, d: Delivery) -> list[Result]:
    p = f"{item}.webhook"
    payload = d.payload if isinstance(d.payload, dict) else {}
    errors = contract.validate_file_schema(d.payload, SCHEMAS[item][1])
    results = [
        Result(item, f"{p}.received", "pass", d.event),
        _result(
            item,
            f"{p}.signature",
            d.signature_ok,
            d.signature_detail,
            d,
        ),
        _result(
            item,
            f"{p}.timestamp",
            d.timestamp_ok,
            f"X-Mervia-Timestamp must be within 300s: {d.timestamp_detail}",
            d,
            ok_detail=d.timestamp_detail,
        ),
        _result(item, f"{p}.schema", not errors, "; ".join(errors), d),
        _result(item, f"{p}.event_id", bool(payload.get("event_id")), "event_id is missing or empty", d),
    ]
    if item == 8:
        order = payload.get("order")
        results.append(
            _result(
                item,
                f"{p}.attribution",
                isinstance(order, dict) and "mervia_attribution" in order,
                "order.mervia_attribution is missing; send the mervia_attr cookie value, or null",
                d,
            )
        )
    store_id = ctx.opts.store_id or ((ctx.store or {}).get("store_id"))
    if store_id is not None:
        got = sid(payload.get("store_id"))
        results.append(
            _result(
                item,
                f"{p}.store_id",
                got == sid(store_id),
                f"store_id is {got!r}, GET /store says {sid(store_id)!r}",
                d,
            )
        )
    return results


def run(ctx: Context, items: set[int]) -> list[Result]:
    """Wait for the deliveries; the receiver was bound and started when the run began.

    Item 11 is optional: after the order event arrives, the checker waits the rest of the
    timeout for a product event only when 11 was named in --items; otherwise it only looks at
    what already arrived.
    """
    receiver = ctx.receiver
    if not ctx.opts.webhook_secret or receiver is None:
        return [
            skip(i, f"{i}.webhook.received", "pass --webhook-secret to receive and verify webhooks")
            for i in sorted(items)
        ]
    ctx.say(
        f"Waiting up to {ctx.opts.webhook_timeout:.0f}s for webhooks on http://{receiver.address}/ : place a test "
        "order on staging" + (" and edit a product" if 11 in items else "") + "."
    )
    deadline = time.monotonic() + ctx.opts.webhook_timeout
    explicit_11 = ctx.opts.items is not None and 11 in ctx.opts.items
    found: dict[int, Delivery | None] = {}
    for item in sorted(items):
        prefix = SCHEMAS[item][0]
        wait = max(0.0, deadline - time.monotonic())
        if item == 11 and 8 in items and not explicit_11:
            wait = 0.0
        found[item] = receiver.wait_for(lambda d, pre=prefix: d.event.startswith(pre), wait)
    results: list[Result] = []
    for item, delivery in found.items():
        if delivery is not None:
            results += _validate(ctx, item, delivery)
            continue
        others = [d for d in receiver.deliveries if not d.event]
        if item == 11:
            results.append(
                skip(
                    11,
                    "11.webhook.received",
                    "no product event arrived during the wait; "
                    "edit a product on staging while the checker waits to test item 11",
                )
            )
        elif others:
            request, response = _exchange(others[0])
            results.append(
                Result(
                    8,
                    "8.webhook.received",
                    "fail",
                    f"{len(others)} delivery(ies) arrived but none was an order event with a JSON body",
                    request,
                    response,
                )
            )
        else:
            results.append(
                Result(
                    8, "8.webhook.received", "fail", f"no order event arrived within {ctx.opts.webhook_timeout:.0f}s"
                )
            )
    return results
