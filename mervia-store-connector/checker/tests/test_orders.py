from fakestore import FakeStore


def _orders(check, *breaks, **opts):
    return check(FakeStore(breaks=breaks), items=[1, 8], **opts)


def test_green_run(check):
    run = _orders(check)
    assert run.failures() == []
    assert run.status("8.orders.schema") == "pass" and "5 orders" in run.get("8.orders.schema").detail
    assert run.status("8.orders.pagination") == "pass" and "7 distinct ids" in run.get("8.orders.pagination").detail
    assert run.status("1.store.auth.no_key.orders") == "pass"
    assert not any(r.warning for r in run.results)
    assert "8.webhook.received" not in [r.name for r in run.results]  # no webhook declared: nothing waited for


def test_no_orders_is_a_warning_not_a_pass(check):
    store = FakeStore()
    store.orders = []
    run = check(store, items=[8])
    assert run.failures() == []
    assert run.get("8.orders.schema").warning and "no orders" in run.get("8.orders.schema").detail


def test_unpaid_order_in_the_list_fails(check):
    run = _orders(check, "orders_unpaid")
    assert run.status("8.orders.schema") == "fail"  # pending is not a known status
    assert run.status("8.orders.paid_only") == "fail"
    assert "pending" in run.get("8.orders.paid_only").detail


def test_refund_over_total_fails_and_partial_cancel_warns(check):
    assert _orders(check, "orders_refund_over").status("8.orders.refunded_total") == "fail"
    partial = _orders(check, "orders_cancel_partial").get("8.orders.refunded_total")
    assert partial.warning and "full refund" in partial.detail


def test_personal_data_fails(check):
    run = _orders(check, "orders_pii")
    assert run.status("8.orders.no_pii") == "fail"
    detail = run.get("8.orders.no_pii").detail
    assert "customer_email (key)" in detail and "(email address)" in detail


def test_ignored_updated_since_fails(check):
    assert _orders(check, "orders_ignore_updated_since").status("8.orders.updated_since") == "fail"


def test_full_page_without_cursor_fails(check):
    run = _orders(check, "orders_no_cursor")
    assert run.status("8.orders.pagination") == "fail"
    assert "next_cursor must point at the rest" in run.get("8.orders.pagination").detail


def test_item_3_needs_orders_or_the_arranged_webhook(check):
    run = check(FakeStore(caps=["products"]), items=[8])
    assert run.status("8.orders") == "fail" and "orders" in run.get("8.orders").detail
    run = check(FakeStore(caps=["products"]))
    assert run.status("8.orders") == "skip"
    run = check(FakeStore(caps=["products", "order_webhook"]), items=[8])  # arranged webhook, no secret given
    assert run.status("8.webhook.received") == "skip"
