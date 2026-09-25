"""Ids are opaque: one with a slash, a space or a percent sign must reach the store as one path segment."""

from fakestore import FakeStore

ODD_ID = "SKU-44/blue 50%"


def _store() -> FakeStore:
    store = FakeStore()
    for p in store.products:  # every product gets an odd id, so whichever the checker picks is odd
        p["id"] = f"{ODD_ID}-{p['handle']}"
    return store


def test_product_reviews_and_content_paths_encode_the_id(check):
    run = check(_store(), items=[2, 3, 6])
    assert run.failures() == []
    assert run.status("2.products.get_one") == "pass"
    assert run.status("3.reviews.schema") == "pass"
    assert run.status("6.push.put") == "pass" and run.status("6.push.removed") == "pass"


def test_product_id_option_is_encoded(check):
    store = _store()
    pid = store.products[3]["id"]
    run = check(store, items=[3, 6], product_id=pid)
    assert run.failures() == []
    assert pid in run.get("6.push.put").detail


def test_article_ids_are_encoded(check):
    store = FakeStore()
    original = store.create_article

    def odd_id(body):
        resp = original(body)
        art = store.articles.pop(resp.json()["id"])
        art["id"] = "a/1 %x"
        art["preview_url"] = art["preview_url"].replace(resp.json()["id"], "a%2F1%20%25x")
        store.articles[art["id"]] = art
        import httpx

        return httpx.Response(201, json=art)

    store.create_article = odd_id
    run = check(store, items=[5])
    assert run.failures() == []
    assert store.conformance_articles == {}
