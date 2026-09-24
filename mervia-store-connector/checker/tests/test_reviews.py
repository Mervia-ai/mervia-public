from fakestore import FakeStore


def test_reviews_pass_on_rated_product(check):
    run = check(FakeStore(), items=[3])
    assert run.failures() == []
    assert "product 102" in run.get("3.reviews.schema").detail  # the product with rating.count > 0


def test_product_id_is_honoured(check):
    run = check(FakeStore(), items=[3], product_id="104")
    assert "product 104" in run.get("3.reviews.schema").detail


def test_no_reviews_is_a_warning(check):
    result = check(FakeStore(breaks=("no_reviews",)), items=[3]).get("3.reviews.schema")
    assert result.status == "pass" and result.warning


def test_email_author_fails(check):
    assert check(FakeStore(breaks=("review_email",)), items=[3]).status("3.reviews.no_email") == "fail"


def test_summary_below_items_fails(check):
    assert check(FakeStore(breaks=("review_count_low",)), items=[3]).status("3.reviews.summary_count") == "fail"


def test_mistyped_product_id_fails(check):
    assert check(FakeStore(), items=[3], product_id="nope").status("3.reviews.schema") == "fail"
