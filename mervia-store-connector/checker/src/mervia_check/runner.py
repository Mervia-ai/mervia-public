"""Decide which items to run from the store's declared capabilities, run them, collect Results."""

from __future__ import annotations

import secrets
import time
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from . import contract
from .checks import (
    Context,
    Options,
    articles,
    body_json,
    content_pull,
    content_push,
    describe,
    orders,
    pages,
    products,
    reviews,
    stderr,
    store,
    tags,
    webhook,
)
from .client import Client
from .receiver.webhook_receiver import WebhookReceiver
from .redact import Redactor, secret_problem
from .report import Result, fail, ok, skip, warn
from .stub.include_stub import IncludeStub

# The capability that declares each item; items 1, 7 and 9 have none and always run. Item 8 is
# `orders` (GET /orders) and, by arrangement with Mervia, `order_webhook` as well or instead.
CAPABILITY = {2: "products", 3: "reviews", 4: "pages", 5: "articles", 11: "product_webhook"}
DEFAULT_ITEMS = [1, 2, 3, 4, 5, 6, 7, 9, 8, 11]
WRITE_ITEMS = {5, 6}
SHORT_NAMES = {
    1: "store",
    2: "products",
    3: "reviews",
    4: "pages",
    5: "articles",
    6: "content",
    7: "tag",
    8: "orders",
    9: "search_console",
    10: "chat_widget",
    11: "webhook",
}


class RunError(Exception):
    """The run could not start: bad option, unreachable store, port in use (exit code 2)."""


def check_options(opts: Options) -> None:
    for label, value in (
        ("--api-key", opts.api_key),
        ("--webhook-secret", opts.webhook_secret),
        ("--public-auth", opts.public_auth),
    ):
        if value is not None and (problem := secret_problem(value)):
            raise RunError(f"{label} {problem}")  # never the value itself
    if opts.public_auth is not None and ":" not in opts.public_auth:
        raise RunError("--public-auth must be USER:PASSWORD")


def _content_check(ctx: Context) -> Callable[[Context], list[Result]] | str:
    """The item-6 check to run, or the reason it is skipped."""
    caps = ctx.capabilities
    mode = ctx.opts.content_mode
    if mode == "auto":
        mode = "pull" if "content_pull" in caps else "push" if "content_push" in caps else ""
        if not mode:
            return "not declared in capabilities (content_pull or content_push)"
    if f"content_{mode}" not in caps:
        return f"--content-mode {mode} but content_{mode} is not declared in capabilities"
    return content_pull.run if mode == "pull" else content_push.run


def _guarded(item: int, check: Callable[[Context], list[Result]], ctx: Context) -> list[Result]:
    """A bug in the checker must not hide the other items' results. Ctrl-C/SIGTERM still propagate."""
    try:
        return check(ctx)
    except Exception as exc:  # noqa: BLE001
        last = traceback.format_exception_only(exc)[-1].strip()
        return [fail(item, f"{item}.checker_error", f"the checker itself failed: {last}")]


def _bind(ctx: Context, selected: list[int]) -> None:
    """Bind the local servers at startup, so a busy port stops the run before any request."""
    opts = ctx.opts
    if opts.webhook_secret and {8, 11} & set(selected):
        try:
            ctx.receiver = WebhookReceiver(opts.webhook_listen, opts.webhook_secret).start()
        except OSError as exc:
            raise RunError(f"cannot start the webhook receiver on {opts.webhook_listen}: {exc}") from exc
        ctx.say(
            f"Webhook receiver listening on http://{ctx.receiver.address}/ . Set the staging store's Mervia "
            "webhook URL to an address that reaches it (replace 0.0.0.0 with a reachable host or tunnel)."
        )
    if opts.include_stub_listen and 6 in selected:
        try:
            ctx.stub = IncludeStub(
                opts.include_stub_listen,
                slow_seconds=content_pull.SLOW_SECONDS,
                token=ctx.run_id,
                on_bearer=ctx.redact.add,
            ).start()
        except OSError as exc:
            raise RunError(f"cannot start the include stub on {opts.include_stub_listen}: {exc}") from exc
        ctx.say(
            f"Include stub listening at http://{ctx.stub.address}/include/v1/ . Point the staging store's "
            "Mervia include base URL at it for this run."
        )


def run(
    opts: Options,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    say: Callable[[str], None] = stderr,
    rate: float = 2.0,
    retry_delay: float = 5.0,
) -> tuple[list[Result], dict[str, Any]]:
    check_options(opts)
    redact = Redactor(opts.api_key, opts.webhook_secret, opts.public_auth)
    client = Client(
        opts.base_url,
        opts.api_key,
        timeout=opts.timeout,
        verify=not opts.insecure,
        rate=rate,
        transport=transport,
        sleep=sleep,
        public_auth=opts.public_auth,
    )
    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(3)
    ctx = Context(
        opts=opts,
        client=client,
        run_id=run_id,
        sleep=sleep,
        retry_delay=retry_delay,
        say=lambda message: say(redact(message)),
        redact=redact,
    )
    meta = {"base_url": redact(opts.base_url), "run_id": run_id, "contract_version": contract.contract_version()}
    try:
        _bind(ctx, opts.items or DEFAULT_ITEMS)
        try:
            resp = client.api("GET", "/store")
        except httpx.HTTPError as exc:
            raise RunError(redact(f"cannot reach {opts.base_url}/store: {exc}")) from exc
        ctx.store_response = resp
        data = body_json(resp)
        if resp.status_code == 200 and isinstance(data, dict):
            ctx.store = data
        return redact.deep(_run_items(ctx)), meta
    finally:
        for server in (ctx.receiver, ctx.stub):
            if server is not None:
                server.stop()
        client.close()


def _preflight(ctx: Context, selected: list[int]) -> list[Result]:
    """Item-1 facts reported whatever --items says: an https base URL and a readable GET /store."""
    results: list[Result] = []
    https = ctx.opts.base_url.lower().startswith("https://")
    if not https and not ctx.opts.allow_http:
        results.append(
            fail(1, "1.store.https", "the base URL must be https (pass --allow-http for a local test store)")
        )
    elif not https:
        results.append(warn(1, "1.store.https", "http base URL accepted because of --allow-http"))
    elif 1 in selected:
        results.append(ok(1, "1.store.https"))
    if ctx.store is None and 1 not in selected:
        resp = ctx.store_response
        results.append(
            fail(1, "1.store.status", f"GET /store did not answer 200 with a JSON object ({describe(resp)})", resp)
        )
    return results


def _run_items(ctx: Context) -> list[Result]:
    explicit = ctx.opts.items is not None
    selected = ctx.opts.items or DEFAULT_ITEMS
    results = _preflight(ctx, selected)
    webhook_items: set[int] = set()
    checks: dict[int, Callable[[Context], list[Result]]] = {
        1: store.run,
        2: products.run,
        3: reviews.run,
        4: pages.run,
        5: articles.run,
        7: tags.run_tag,
        9: tags.run_search_console,
    }
    for item in [i for i in DEFAULT_ITEMS + [10] if i in selected]:
        name = f"{item}.{SHORT_NAMES[item]}"
        if item == 10:
            results.append(skip(10, "10.chat_widget", "not checked yet (the chat widget tag comes later)"))
            continue
        if item != 1 and ctx.store is None:
            results.append(skip(item, name, "GET /store did not answer 200, so the declared capabilities are unknown"))
            continue
        if item == 8:
            has_orders, has_hook = "orders" in ctx.capabilities, "order_webhook" in ctx.capabilities
            if not has_orders and not has_hook:
                reason = "not declared in capabilities (orders)"
                results.append(fail(8, name, f"requested but {reason}") if explicit else skip(8, name, reason))
                continue
            if has_orders:
                results += _guarded(8, orders.run, ctx)
            if has_hook:
                webhook_items.add(8)
            continue
        capability = CAPABILITY.get(item)
        if capability and capability not in ctx.capabilities:
            if item == 11 and not explicit:
                continue  # by arrangement only: nothing to report unless the store declares it or --items names it
            if explicit:
                results.append(fail(item, name, f"requested but not declared in capabilities ({capability})"))
            else:
                results.append(skip(item, name, f"not declared in capabilities ({capability})"))
            continue
        if item in WRITE_ITEMS and not ctx.opts.allow_writes:
            results.append(
                skip(item, name, "writes to the store; pass --allow-writes to run it (against a STAGING store only)")
            )
            continue
        if item == 11:
            webhook_items.add(item)
        elif item == 6:
            content = _content_check(ctx)
            if isinstance(content, str):
                undeclared = explicit and "not declared" in content
                results.append(
                    (fail if undeclared else skip)(
                        6, "6.content", content if not undeclared else f"requested but {content}"
                    )
                )
            else:
                results += _guarded(6, content, ctx)
        else:
            results += _guarded(item, checks[item], ctx)
    if webhook_items:  # last, because it waits for the merchant to place an order
        results += _guarded(8, lambda c: webhook.run(c, webhook_items), ctx)
    return results
