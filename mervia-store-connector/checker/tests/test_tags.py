from fakestore import FakeStore

from mervia_check.checks.tags import attributes, mervia_tags


def test_attribute_order_and_quoting_agnostic():
    page = "<script data-store='s1' defer src=https://app.mervia.ai/tag/v1/mervia.js></script>"
    assert mervia_tags(page)[0]["data-store"] == "s1"
    assert attributes("a=\"1\" B='2' c=3 d")["b"] == "2"
    assert mervia_tags(f"<!-- {page} -->") == []


def test_tag_passes(check):
    run = check(FakeStore(), items=[7], store_id="example-us")
    assert run.failures() == []
    assert run.status("7.tag.product_page") == "pass"


def test_missing_tag_fails(check):
    assert check(FakeStore(breaks=("no_tag",)), items=[7]).status("7.tag.present") == "fail"


def test_commented_out_tag_fails(check):
    assert check(FakeStore(breaks=("tag_commented",)), items=[7]).status("7.tag.present") == "fail"


def test_wrong_store_fails(check):
    assert (
        check(FakeStore(breaks=("wrong_store",)), items=[7], store_id="example-us").status("7.tag.store_id") == "fail"
    )


def test_search_console_present_passes(check):
    assert check(FakeStore(), items=[9]).status("9.search_console.meta") == "pass"


def test_search_console_absent_skips(check):
    run = check(FakeStore(breaks=("no_gsv",)), items=[9])
    assert run.status("9.search_console.meta") == "skip"
    assert "not yet placed" in run.get("9.search_console.meta").detail


def test_public_base_url_override(check):
    assert (
        check(FakeStore(), items=[7], public_base_url="https://staging.example.com/").status("7.tag.present") == "pass"
    )


def test_staging_run_accepts_the_staging_tag_only(check):
    run = check(FakeStore(breaks=("staging_tag",)), items=[7], store_id="example-us", mervia_env="staging")
    assert run.failures() == []
    assert run.get("7.tag.present").detail == "staging tag"
    run = check(FakeStore(), items=[7], mervia_env="staging")
    assert run.status("7.tag.present") == "fail"
    assert "staging-marketing.mervia.ai" in run.get("7.tag.present").detail
    assert "production tag instead" in run.get("7.tag.present").detail


def test_production_run_names_a_staging_tag(check):
    run = check(FakeStore(breaks=("staging_tag",)), items=[7])
    assert run.status("7.tag.present") == "fail"
    detail = run.get("7.tag.present").detail
    assert "staging tag instead" in detail and "--mervia-env" in detail
    assert run.status("7.tag.product_page") == "fail"
