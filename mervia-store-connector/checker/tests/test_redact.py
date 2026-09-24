import base64

from mervia_check.redact import Redactor, secret_problem
from mervia_check.report import Result


def test_secret_problems():
    assert secret_problem("abc\r") and secret_problem(" abc") and secret_problem("a\x00b") and secret_problem("")
    assert secret_problem("fine-key") is None


def test_redactor_masks_raw_json_and_basic_forms():
    r = Redactor('key"with-quote', None, "user:passw0rd")
    basic = base64.b64encode(b"user:passw0rd").decode()
    text = 'k=key"with-quote j=key\\"with-quote b=' + basic + " p=passw0rd"
    assert r(text) == "k=*** j=*** b=*** p=***"


def test_deep_scrubs_results():
    r = Redactor("topsecret")
    result = Result(
        1, "1.x", "fail", "saw topsecret", {"url": "https://x/?k=topsecret", "headers": {}}, {"body": ["topsecret"]}
    )
    clean = r.deep([result])[0]
    assert "topsecret" not in repr(clean)


def test_short_values_are_not_masked():
    assert Redactor("ab")("ab cd") == "ab cd"
