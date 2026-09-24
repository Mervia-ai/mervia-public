import httpx
import pytest
from fakestore import FakeStore


def test_push_passes_and_removes(check):
    store = FakeStore()
    run = check(store, items=[6])
    assert run.failures() == []
    assert store.content == {}


def test_product_id_option_is_used(check):
    run = check(FakeStore(), items=[6], product_id="104")
    assert "product 104" in run.get("6.push.put").detail


def test_mistyped_product_id_fails(check):
    assert check(FakeStore(), items=[6], product_id="nope").status("6.push.put") == "fail"


@pytest.mark.parametrize(
    "defect, name",
    [
        ("push_ignored", "6.push.rendered"),
        ("push_rewrites", "6.push.rendered"),
        ("push_not_removed", "6.push.removed"),
        ("push_in_body", "6.push.in_head"),
    ],
)
def test_each_defect_is_caught(check, defect, name):
    assert check(FakeStore(breaks=(defect,)), items=[6]).status(name) == "fail"


def test_existing_document_is_left_alone_unless_named(check):
    store = FakeStore()
    real = {
        "version": 9,
        "head_html": '<script id="mervia-product-schema">{}</script>',
        "body_html": '<section id="mervia-shopping-guide">real</section>',
    }
    store.content["101"] = real
    run = check(store, items=[6])
    assert run.status("6.push.put") == "skip"
    assert store.content["101"] is real
    assert check(store, items=[6], product_id="101").status("6.push.put") == "pass"


def test_cleanup_after_failed_delete(check):
    store = FakeStore()
    inner = store.handle
    deletes = []

    def handle(request):
        if request.method == "DELETE" and not deletes:
            deletes.append(1)
            return httpx.Response(500)
        return inner(request)

    store.handle = handle
    run = check(store, items=[6])
    assert run.status("6.push.delete") == "fail"
    assert run.status("6.push.cleanup") == "pass"
    assert store.content == {}


def test_forced_mode_that_is_not_declared(check):
    caps = ["products", "content_pull"]
    assert check(FakeStore(caps=caps), content_mode="push").status("6.content") == "skip"
    assert check(FakeStore(caps=caps), items=[6], content_mode="push").status("6.content") == "fail"


def test_writes_need_allow_writes(check):
    store = FakeStore()
    run = check(store, items=[6, 5], allow_writes=False)
    assert run.status("6.content") == "skip" and "--allow-writes" in run.get("6.content").detail
    assert run.status("5.articles") == "skip"
    assert store.conformance_articles == {} and store.content == {}
