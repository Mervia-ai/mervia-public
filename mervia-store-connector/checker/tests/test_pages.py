from fakestore import FakeStore


def test_pages_pass(check):
    assert check(FakeStore(), items=[4]).failures() == []


def test_unknown_kind_fails(check):
    run = check(FakeStore(breaks=("bad_page_kind",)), items=[4])
    assert run.status("4.pages.kinds") == "fail"
    assert run.status("4.pages.schema") == "fail"
