"""One scrubber for every string that leaves the checker: report, stderr messages, errors.

It replaces the API key, the probe key sent to test 401s, the webhook secret, the include
bearer the stub received and the public-site credentials with `***`, in their raw form and in
the forms they take once JSON-escaped or Basic-encoded.
"""

from __future__ import annotations

import base64
import json
import threading
from dataclasses import fields, replace
from typing import Any, TypeVar

MASK = "***"
MIN_SECRET_LENGTH = 4  # shorter values would mask ordinary text
T = TypeVar("T")


def secret_problem(value: str) -> str | None:
    """Why a secret given on the command line is unusable, without echoing it; None when fine."""
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        return "contains a control character (a stray newline or carriage return?)"
    if value != value.strip():
        return "has leading or trailing whitespace"
    if not value:
        return "is empty"
    return None


class Redactor:
    def __init__(self, *secrets: str | None) -> None:
        self._secrets: set[str] = set()
        self._lock = threading.Lock()
        self.add(*secrets)

    def add(self, *values: str | None) -> None:
        with self._lock:
            for value in values:
                if not value or len(value) < MIN_SECRET_LENGTH:
                    continue
                forms = {value, json.dumps(value)[1:-1]}
                if ":" in value:  # user:pass for the public site
                    forms.add(base64.b64encode(value.encode()).decode())
                    password = value.split(":", 1)[1]
                    if len(password) >= MIN_SECRET_LENGTH:
                        forms.add(password)
                self._secrets |= forms

    def __call__(self, text: str) -> str:
        with self._lock:
            secrets = sorted(self._secrets, key=len, reverse=True)
        for secret in secrets:
            text = text.replace(secret, MASK)
        return text

    def deep(self, value: Any) -> Any:
        """Scrub every string inside dicts, lists and dataclasses."""
        if isinstance(value, str):
            return self(value)
        if isinstance(value, dict):
            return {self.deep(k): self.deep(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return type(value)(self.deep(v) for v in value)
        if hasattr(value, "__dataclass_fields__"):
            return replace(value, **{f.name: self.deep(getattr(value, f.name)) for f in fields(value)})
        return value
