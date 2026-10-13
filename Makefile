.PHONY: lint test boot smoke
PORT ?= 5004
lint:
	.venv/bin/ruff check backend/
test:
	@TMP=$$(mktemp -d); trap 'rm -rf "$$TMP"' EXIT; \
	 REVIEW_ISOLATED_RUN=1 UPLOAD_WORKER_ENABLED=0 UPLOAD_ROOT="$$TMP/uploads" DATABASE_PATH="$$TMP/test.sqlite3" .venv/bin/pytest -q --cov=backend --cov-report=term-missing --cov-fail-under=95.97
smoke:
	REVIEW_ISOLATED_RUN=1 UPLOAD_WORKER_ENABLED=0 .venv/bin/python -c "import tempfile, os; os.environ['DATABASE_PATH']=tempfile.mktemp(); from backend.app import create_app; assert create_app().test_client().get('/health').status_code == 200"

boot:
	PORT=$(PORT) .venv/bin/python backend/app.py
