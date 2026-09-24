import httpx
import pytest
from conftest import free_port
from fakestore import INCLUDE_KEY, FakeStore

from mervia_check import contract
from mervia_check.checks import content_pull
from mervia_check.stub.include_stub import IncludeStub, document

PULL_CAPS = ["products", "content_pull"]


def test_stub_document_matches_include_schema():
    assert contract.validate_file_schema(document(3, "tok"), "include-response.schema.json") == []


def test_stub_modes_and_paths():
    seen = []
    stub = IncludeStub("127.0.0.1:0", slow_seconds=0.2, on_bearer=seen.append).start()
    base = f"http://{stub.address}/include/v1"
    url = f"{base}/k/products/1"
    stub.expect({"1"})
    try:
        ok = httpx.get(url, headers={"Authorization": "Bearer abcd1234"})
        assert ok.status_code == 200 and ok.headers["ETag"] == '"1"'
        assert httpx.get(url, headers={"If-None-Match": '"1"'}).status_code == 304
        assert httpx.get(f"{base}/k/products/2").status_code == 404  # not an expected product
        assert httpx.get(f"{base}/products/1").status_code == 404  # no store key
        stub.set_mode("error")
        assert httpx.get(url).status_code == 500
        stub.set_mode("notfound")
        assert httpx.get(url).status_code == 404
        stub.set_mode("slow")
        with pytest.raises(httpx.TimeoutException):
            httpx.get(url, timeout=0.05)
        assert seen == ["abcd1234"]
        assert "abcd1234" not in repr(stub.requests)
        assert stub.bearer_in("x abcd1234 y") and not stub.bearer_in("nothing")
        with pytest.raises(ValueError):
            stub.set_mode("bogus")
    finally:
        stub.stop()


def _pull(check, *breaks, include_cache=False, **opts):
    port = free_port()
    store = FakeStore(
        caps=PULL_CAPS, breaks=breaks, include_url=f"http://127.0.0.1:{port}/include/v1/", include_cache=include_cache
    )
    return check(store, items=[6], include_stub_listen=f"127.0.0.1:{port}", **opts)


def test_pull_passes(check):
    run = _pull(check)
    assert run.failures() == []
    assert run.status("6.pull.slow") == "pass" and "product 102" in run.get("6.pull.slow").detail
    assert run.status("6.pull.error") == "pass"
    assert run.status("6.pull.error_no_copy") == "pass" and "product 103" in run.get("6.pull.error_no_copy").detail
    assert "ids are gone" in run.get("6.pull.notfound").detail


def test_caching_store_gets_a_warning_where_the_cache_hides_the_error_path(check):
    """A store that caches each product for 15 minutes, as the contract says, never re-fetches product A."""
    run = _pull(check, include_cache=True)
    assert run.failures() == []
    assert run.get("6.pull.error").warning
    assert "did not call the include" in run.get("6.pull.error").detail
    assert run.status("6.pull.error_no_copy") == "pass"


def test_cache_cannot_hide_a_store_that_fails_without_a_last_good_copy(check):
    run = _pull(check, "pull_no_last_good", include_cache=True)
    assert run.get("6.pull.error").warning  # the cache served the copy; the phase proved nothing
    assert run.status("6.pull.error_no_copy") == "fail"
    assert "render the page without the document" in run.get("6.pull.error_no_copy").detail
    assert any("/include/v1/" in m for m in run.messages)
    assert not any(INCLUDE_KEY in m for m in run.messages)


def test_client_side_include_fails(check):
    run = _pull(check, "pull_client_side")
    assert run.status("6.pull.rendered") == "fail"
    assert "server" in run.get("6.pull.rendered").detail


def test_copy_from_before_the_run_fails_and_skips_the_phases(check):
    run = _pull(check, "pull_cached")
    assert run.status("6.pull.rendered") == "fail"
    assert "no request at all" in run.get("6.pull.rendered").detail
    for mode in ("slow", "error", "error_no_copy", "notfound"):
        assert run.status(f"6.pull.{mode}") == "skip"


def test_internal_id_in_include_path_fails(check):
    run = _pull(check, "pull_internal_id")
    assert run.status("6.pull.include_path") == "fail"
    assert "widget-1" in run.get("6.pull.include_path").detail


def test_missing_include_key_fails(check):
    assert _pull(check, "pull_no_bearer").status("6.pull.include_key") == "fail"


def test_include_key_in_page_html_fails_and_is_never_printed(check):
    run = _pull(check, "pull_key_in_html")
    assert run.status("6.pull.include_key_private") == "fail"
    assert INCLUDE_KEY not in repr(run.results)


def test_no_last_good_fails(check):
    run = _pull(check, "pull_no_last_good")
    assert run.status("6.pull.error") == "fail"
    assert run.status("6.pull.error_no_copy") == "fail"
    assert run.status("6.pull.slow") == "fail"


def test_no_include_timeout_fails(check, monkeypatch):
    monkeypatch.setattr(content_pull, "SLOW_SECONDS", 3.5)  # still over the 2.5 s budget, keeps the test short
    run = _pull(check, "pull_no_timeout")
    assert run.status("6.pull.slow") == "fail"
    assert "1-second include timeout" in run.get("6.pull.slow").detail


def test_store_not_pointed_at_stub_fails_with_instructions(check):
    store = FakeStore(caps=PULL_CAPS, include_url=f"http://127.0.0.1:{free_port()}/include/v1/")
    run = check(store, items=[6], include_stub_listen=f"127.0.0.1:{free_port()}")
    assert run.status("6.pull.rendered") == "fail"
    assert "include base URL" in run.get("6.pull.rendered").detail


def test_pull_without_stub_listen_skips(check):
    assert check(FakeStore(caps=PULL_CAPS), items=[6]).status("6.pull.rendered") == "skip"
