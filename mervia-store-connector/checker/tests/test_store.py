from fakestore import KEY, FakeStore


def test_store_passes(check):
    run = check(FakeStore(), items=[1], store_id="example-us")
    assert run.failures() == []
    for name in (
        "1.store.https",
        "1.store.auth.wrong_key",
        "1.store.auth.no_key.products",
        "1.store.auth.no_key.articles",
        "1.store.auth.no_key.article_patch",
        "1.store.auth.no_key.article_delete",
    ):
        assert run.status(name) == "pass"


def test_probe_key_is_random_and_same_length(check):
    store = FakeStore()
    check(store, items=[1])
    probes = [h for h in store.auth_headers if h and h != f"Bearer {KEY}"]
    assert probes and all(len(h) == len(f"Bearer {KEY}") for h in probes)


def test_bad_key_accepted_fails(check):
    run = check(FakeStore(breaks=("no_401",)), items=[1])
    assert run.status("1.store.auth.wrong_key") == "fail"
    assert run.status("1.store.auth.no_key") == "fail"
    assert KEY not in str(run.get("1.store.auth.wrong_key").request)


def test_401_only_on_store_is_caught(check):
    run = check(FakeStore(breaks=("auth_only_store",)), items=[1])
    assert run.status("1.store.auth.no_key") == "pass"
    for name in (
        "1.store.auth.no_key.products",
        "1.store.auth.no_key.articles",
        "1.store.auth.no_key.article_patch",
        "1.store.auth.no_key.article_delete",
    ):
        assert run.status(name) == "fail", name
    assert "got 404" in run.get("1.store.auth.no_key.article_patch").detail


def test_both_content_modes_fail(check):
    assert check(FakeStore(breaks=("both_content",)), items=[1]).status("1.store.capabilities") == "fail"


def test_schema_violation_fails(check):
    run = check(FakeStore(breaks=("bad_store_schema",)), items=[1])
    assert run.status("1.store.schema") == "fail"
    assert "currency" in run.get("1.store.schema").detail


def test_store_id_mismatch_fails(check):
    assert check(FakeStore(), items=[1], store_id="other").status("1.store.store_id") == "fail"


def test_unknown_capability_fails(check):
    assert check(FakeStore(caps=["products", "teleport"]), items=[1]).status("1.store.capabilities") == "fail"


def test_undeclared_items_skip_by_default(check):
    run = check(FakeStore(caps=["products"]))
    for name in ("3.reviews", "5.articles", "4.pages", "6.content"):
        assert run.status(name) == "skip", name
        assert "not declared" in run.get(name).detail


def test_requested_but_undeclared_items_fail(check):
    run = check(FakeStore(caps=["products"]), items=[1, 3, 5, 4, 6])
    for name in ("3.reviews", "5.articles", "4.pages", "6.content"):
        assert run.status(name) == "fail", name
        assert "requested but" in run.get(name).detail


def test_failed_store_read_fails_even_without_item_1():
    from fakestore import API

    from mervia_check.checks import Options
    from mervia_check.runner import run

    store = FakeStore()
    results, _ = run(
        Options(base_url=API, api_key="wrong-key", items=[2, 5]),
        transport=store.transport(),
        sleep=lambda _s: None,
        say=lambda _m: None,
        rate=0,
    )
    assert [r.name for r in results if r.status == "fail"] == ["1.store.status"]


def test_http_base_url_fails_unless_allowed(check):
    from fakestore import API

    http = API.replace("https://", "http://")
    assert check(FakeStore(), items=[1], base_url=http).status("1.store.https") == "fail"
    assert check(FakeStore(), items=[2], base_url=http).status("1.store.https") == "fail"  # whatever --items says
    allowed = check(FakeStore(), items=[1], base_url=http, allow_http=True)
    assert allowed.get("1.store.https").warning and allowed.failures() == []
