import json

from mervia_check.report import Result, exit_code, go_live_line, render_json, render_text, summary, warn

META = {"base_url": "https://x.test", "run_id": "r", "contract_version": "1"}


def test_exit_code_and_summary():
    results = [Result(1, "1.a", "pass"), warn(1, "1.b", "blocked"), Result(2, "2.a", "skip")]
    assert exit_code(results) == 0
    assert summary(results) == {"pass": 2, "warn": 1, "fail": 0, "skip": 1}
    assert exit_code(results + [Result(2, "2.b", "fail", "bad")]) == 1


def test_go_live_line():
    checked = [Result(i, f"{i}.x", "pass") for i in (1, 2, 3, 5, 6, 7, 8)]
    assert go_live_line(checked) == "GO-LIVE: COMPLETE (items 1, 2, 3, 5, 6, 7, 8 checked)"
    partial = checked[:5] + [Result(7, "7.x", "skip"), Result(8, "8.x", "skip")]
    assert go_live_line(partial) == "GO-LIVE: INCOMPLETE (7, 8 not checked)"


def test_text_report_orders_by_item_and_shows_failing_exchange():
    failing = Result(
        2,
        "2.x",
        "fail",
        "boom",
        {"method": "GET", "url": "https://x.test/p", "headers": {}, "body": ""},
        {"status": 500, "headers": {}, "body": "oops"},
    )
    text = render_text([failing, Result(1, "1.a", "pass"), warn(4, "4.w", "hm")], META)
    assert text.index("Item 1") < text.index("Item 2") < text.index("Item 4")
    assert "GET https://x.test/p" in text and "oops" in text and "WARN  4.w  hm" in text
    assert "RESULT: FAIL" in text and "GO-LIVE: INCOMPLETE (3, 5, 6, 7, 8 not checked)" in text


def test_json_report_round_trips():
    data = json.loads(render_json([Result(1, "1.a", "pass", "fine")], META))
    assert data["summary"]["pass"] == 1 and data["results"][0]["name"] == "1.a"
    assert data["go_live"] == {"complete": False, "not_checked": [2, 3, 5, 6, 7, 8]}
