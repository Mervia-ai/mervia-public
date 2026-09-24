import httpx
import pytest
from fakestore import FakeStore


def test_lifecycle_passes_and_cleans_up(check):
    store = FakeStore()
    run = check(store, items=[5])
    assert run.failures() == []
    assert [r for r in run.results if r.warning] == []
    assert store.conformance_articles == {}
    assert "art-0" in store.articles  # the store's own post is untouched
    assert any("about to WRITE" in m for m in run.messages)


def test_created_article_is_tagged(check):
    store = FakeStore(breaks=("delete_noop",))
    check(store, items=[5])
    (art,) = store.conformance_articles.values()
    assert art["tags"] == ["mervia", "mervia-conformance"]
    assert "Mervia conformance check" in art["title"]


@pytest.mark.parametrize(
    "defect, name",
    [
        ("create_published", "5.articles.create_hidden"),
        ("hidden_public", "5.articles.hidden_not_public"),
        ("hidden_in_sitemap", "5.articles.hidden_not_in_sitemap"),
        ("preview_no_auth", "5.articles.preview"),
        ("preview_open", "5.articles.preview_requires_key"),
        ("tag_filter_ignored", "5.articles.tag_filter"),
        ("publish_not_public", "5.articles.published_public"),
        ("digest_on_publish", "5.articles.digest_stable_on_publish"),
        ("digest_static", "5.articles.digest_changes_on_edit"),
        ("unpublish_stays_public", "5.articles.unpublished_not_public"),
        ("delete_noop", "5.articles.gone"),
    ],
)
def test_each_defect_is_caught(check, defect, name):
    run = check(FakeStore(breaks=(defect,)), items=[5])
    assert run.status(name) == "fail", run.failures()


def test_create_failure_aborts_and_sweep_finds_nothing(check):
    run = check(FakeStore(breaks=("create_500",)), items=[5])
    assert run.status("5.articles.create") == "fail"
    assert run.status("5.articles.remaining") == "skip"
    assert run.get("5.articles.cleanup").detail == "nothing was left behind"


def test_lost_post_response_is_swept_up(check):
    store = FakeStore(breaks=("create_timeout",))
    run = check(store, items=[5])
    assert run.status("5.articles.create") == "fail"
    assert run.status("5.articles.cleanup") == "pass"
    assert store.conformance_articles == {}


def test_cleanup_runs_after_a_mid_lifecycle_abort(check):
    store = FakeStore()
    inner = store.handle

    def handle(request):
        if request.method == "PATCH" and b"published" in request.content:
            return httpx.Response(500, json={"error": "boom"})
        return inner(request)

    store.handle = handle
    run = check(store, items=[5])
    assert run.status("5.articles.publish") == "fail"
    assert run.status("5.articles.cleanup") == "pass"
    assert store.conformance_articles == {}


def test_interrupt_still_cleans_up(check):
    """SIGTERM is turned into KeyboardInterrupt; the lifecycle's finally must still remove the article."""
    store = FakeStore()
    inner = store.handle
    fired = []

    def handle(request):
        if request.method == "PATCH" and b"published" in request.content and not fired:
            fired.append(1)
            raise KeyboardInterrupt
        return inner(request)

    store.handle = handle
    with pytest.raises(KeyboardInterrupt):
        check(store, items=[5])
    assert store.conformance_articles == {}


def test_delete_that_does_not_delete_fails_loudly(check):
    run = check(FakeStore(breaks=("delete_noop",)), items=[5])
    assert run.status("5.articles.gone") == "fail"
    assert run.status("5.articles.cleanup") == "fail"
    assert "still finds the article" in run.get("5.articles.cleanup").detail
    assert any("CLEANUP FAILED" in m for m in run.messages)


def test_cleanup_failure_reported_when_delete_refused(check):
    store = FakeStore()
    inner = store.handle
    store.handle = lambda r: httpx.Response(500, json={"error": "nope"}) if r.method == "DELETE" else inner(r)
    run = check(store, items=[5])
    assert run.status("5.articles.delete") == "fail"
    assert run.status("5.articles.cleanup") == "fail"
    assert any("CLEANUP FAILED" in m for m in run.messages)


def test_stale_sitemap_downgrades_both_sitemap_checks(check):
    run = check(FakeStore(breaks=("stale_sitemap",)), items=[5])
    assert run.get("5.articles.published_in_sitemap").warning
    hidden = run.get("5.articles.hidden_not_in_sitemap")
    assert hidden.warning and "stale" in hidden.detail
    assert run.failures() == []


def test_unreadable_child_sitemap_is_a_warning(check):
    run = check(FakeStore(breaks=("broken_child_sitemap",)), items=[5])
    assert "child sitemap" in run.get("5.articles.hidden_not_in_sitemap").detail
    assert run.get("5.articles.hidden_not_in_sitemap").warning


def test_no_sitemap_is_a_warning(check):
    store = FakeStore()
    inner = store.handle
    store.handle = lambda r: httpx.Response(404) if r.url.path == "/sitemap.xml" else inner(r)
    run = check(store, items=[5])
    assert "no sitemap" in run.get("5.articles.hidden_not_in_sitemap").detail
    assert run.failures() == []
