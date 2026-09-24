.PHONY: sync-contract test lint

sync-contract:
	python3 scripts/sync_contract.py

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check .
