import json
import signal

import httpx
import pytest
from click.testing import CliRunner
from fakestore import API, KEY, FakeStore

from mervia_check import cli
from mervia_check.cli import main


def invoke(store, *args, transport=None, key=KEY):
    obj = {"transport": transport or store.transport(), "sleep": lambda _s: None, "rate": 0}
    return CliRunner().invoke(main, ["--base-url", API, "--api-key", key, *args], obj=obj)


def test_green_run_exits_0_and_never_prints_the_key():
    result = invoke(FakeStore(), "--store-id", "example-us")
    assert result.exit_code == 0, result.output
    assert "RESULT: PASS" in result.output
    assert "GO-LIVE: INCOMPLETE (5, 6 not checked)" in result.output  # no --allow-writes: articles and content skipped
    assert KEY not in result.output


def test_writes_need_the_flag_and_announce_themselves():
    store = FakeStore()
    assert "--allow-writes" in invoke(store, "--items", "5").output
    assert store.conformance_articles == {}
    result = invoke(store, "--items", "5", "--allow-writes")
    assert result.exit_code == 0, result.output
    assert "about to WRITE to staging.example.com" in result.output
    assert "This must be a STAGING store" in result.output


def test_failure_exits_1():
    assert invoke(FakeStore(breaks=("no_tag",)), "--items", "7").exit_code == 1


def test_wrong_key_with_items_that_skip_item_1_exits_1():
    result = invoke(FakeStore(), "--items", "2,5", key="wrong-key-x")
    assert result.exit_code == 1
    assert "1.store.status" in result.output and "RESULT: FAIL" in result.output


def test_json_report_to_file(tmp_path):
    out = tmp_path / "r.json"
    result = invoke(FakeStore(), "--items", "1,4", "--report", "json", "--output", str(out))
    assert result.exit_code == 0
    data = json.loads(out.read_text())
    assert {r["item"] for r in data["results"]} == {1, 4}
    assert KEY not in out.read_text()


def test_echoed_authorization_never_reaches_the_report():
    result = invoke(FakeStore(breaks=("echo_auth",)), "--items", "1,4", "--report", "json")
    assert result.exit_code == 1
    assert KEY not in result.output
    data = json.loads(result.output[result.output.index("{") :])
    bodies = " ".join(r["response"]["body"] for r in data["results"] if r["response"])
    assert "got Authorization: Bearer ***" in bodies


@pytest.mark.parametrize("bad", ["secretvalue123\r", " secretvalue123", "secret\nvalue123"])
def test_bad_key_characters_exit_2_without_echo(bad):
    result = invoke(FakeStore(), key=bad)
    assert result.exit_code == 2
    assert "secretvalue123" not in result.output and "value123" not in result.output


def test_public_auth_is_never_printed():
    result = invoke(FakeStore(breaks=("basic_auth_site",)), "--items", "7", "--public-auth", "stageuser:hunter2pass")
    assert result.exit_code == 0, result.output
    assert "hunter2pass" not in result.output


def test_connection_error_exits_2():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    result = invoke(FakeStore(), transport=httpx.MockTransport(refuse))
    assert result.exit_code == 2
    assert "cannot reach" in result.output


def test_usage_errors_exit_2():
    assert invoke(FakeStore(), "--items", "1,x").exit_code == 2
    assert invoke(FakeStore(), "--items", "12").exit_code == 2
    assert invoke(FakeStore(), "--webhook-listen", "nope").exit_code == 2
    assert invoke(FakeStore(), "--public-auth", "nocolon").exit_code == 2
    assert CliRunner().invoke(main, []).exit_code == 2


def test_default_items_follow_capabilities():
    result = invoke(FakeStore(caps=["products"]))
    assert "3.reviews" in result.output and "not declared in capabilities" in result.output
    assert result.exit_code == 0


def test_bad_key_store_skips_the_rest():
    result = invoke(FakeStore(), key="wrong-key-x")
    assert result.exit_code == 1
    assert "capabilities are unknown" in result.output


def test_sigterm_unwinds_like_ctrl_c():
    with pytest.raises(KeyboardInterrupt):
        cli._on_sigterm(signal.SIGTERM, None)


def test_interrupt_exits_130():
    store = FakeStore()
    inner = store.handle

    def handle(request):
        if request.method == "PATCH":
            raise KeyboardInterrupt
        return inner(request)

    result = invoke(store, "--items", "5", "--allow-writes", transport=httpx.MockTransport(handle))
    assert result.exit_code == 130
    assert "interrupted" in result.output
