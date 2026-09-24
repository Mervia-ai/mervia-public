import httpx
import pytest
from fakestore import FakeStore


def test_products_pass(check):
    run = check(FakeStore(), items=[2])
    assert run.failures() == []
    assert "7 distinct ids" in run.get("2.products.pagination").detail


@pytest.mark.parametrize(
    "defect, name",
    [
        ("dup_pages", "2.products.pagination"),
        ("no_cursor", "2.products.pagination"),
        ("ignore_updated_since", "2.products.updated_since"),
        ("updated_since_empty", "2.products.updated_since_past"),
        ("get_mismatch", "2.products.get_one"),
        ("http_url", "2.products.url_https"),
        ("page_no_title", "2.products.public_page"),
        ("unstable_ids", "2.products.ids_stable"),
        ("no_404", "2.products.not_found"),
    ],
)
def test_each_defect_is_caught(check, defect, name):
    run = check(FakeStore(breaks=(defect,)), items=[2])
    assert run.status(name) == "fail", run.failures()
    assert run.get(name).request is not None or defect == "http_url"


def test_catalog_of_exactly_one_page_passes():
    store = FakeStore(breaks=("no_cursor",))
    store.products = store.products[:5]
    from fakestore import API, KEY

    from mervia_check.checks import Options
    from mervia_check.runner import run

    results, _ = run(
        Options(base_url=API, api_key=KEY, items=[2]),
        transport=store.transport(),
        sleep=lambda _s: None,
        say=lambda _m: None,
        rate=0,
    )
    assert next(r for r in results if r.name == "2.products.pagination").status == "pass"


def test_http_url_also_fails_schema(check):
    assert check(FakeStore(breaks=("http_url",)), items=[2]).status("2.products.schema") == "fail"


def test_blocked_public_page_is_a_warning(check):
    store = FakeStore()
    inner = store.handle
    store.handle = lambda r: httpx.Response(403) if "/api/" not in str(r.url) else inner(r)
    result = check(store, items=[2]).get("2.products.public_page")
    assert result.status == "pass" and result.warning


def test_public_auth_reaches_a_basic_auth_site(check):
    store = FakeStore(breaks=("basic_auth_site",))
    assert check(store, items=[2]).get("2.products.public_page").warning  # 401: blocked
    run = check(FakeStore(breaks=("basic_auth_site",)), items=[2, 7], public_auth="stageuser:hunter2pass")
    assert run.failures() == [] and not run.get("2.products.public_page").warning
