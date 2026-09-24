"""Refresh the contract copy bundled inside the package from the repository's contract/.

The checker ships its own copy of the contract so that `pip install` and the Docker image work
without the repository around them. Run this (or `make sync-contract`) after any change under
contract/; tests/test_contract.py fails while the two copies differ.
"""

from __future__ import annotations

import shutil
from pathlib import Path

CHECKER = Path(__file__).resolve().parent.parent
SOURCE = CHECKER.parent / "contract"
TARGET = CHECKER / "src" / "mervia_check" / "contract"


def main() -> None:
    (TARGET / "schemas").mkdir(parents=True, exist_ok=True)
    for old in (TARGET / "schemas").glob("*.json"):
        old.unlink()
    shutil.copyfile(SOURCE / "openapi.yaml", TARGET / "openapi.yaml")
    for schema in sorted((SOURCE / "schemas").glob("*.json")):
        shutil.copyfile(schema, TARGET / "schemas" / schema.name)
        print(f"copied schemas/{schema.name}")
    print("copied openapi.yaml")


if __name__ == "__main__":
    main()
