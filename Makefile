.PHONY: lint test boot
PORT ?= 5004
lint:
	.venv/bin/ruff check backend/
test:
	@TMP=$$(mktemp -d); trap 'rm -rf "$$TMP"' EXIT; \
	 REVIEW_ISOLATED_RUN=1 UPLOAD_WORKER_ENABLED=0 UPLOAD_ROOT="$$TMP/uploads" DATABASE_PATH="$$TMP/test.sqlite3" .venv/bin/pytest -q --cov=backend --cov-report=term-missing --cov-fail-under=95.97
boot:
	PORT=$(PORT) .venv/bin/python backend/app.py
