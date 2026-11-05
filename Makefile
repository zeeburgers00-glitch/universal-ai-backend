# Shortcuts for the things you actually type.
.PHONY: help install test run docker docker-down backup audit sdk lint

help:
	@echo "make install   - venv + dependencies"
	@echo "make test      - full test suite"
	@echo "make run       - serve on :8000 (needs BACKEND_API_KEY)"
	@echo "make docker    - docker compose up --build"
	@echo "make backup    - request a data backup over HTTP"
	@echo "make audit     - dependency audit (requirements vs imports)"
	@echo "make sdk       - regenerate the Python client SDK"

install:
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

test:
	.venv/bin/python -m pytest -q

run:
	BACKEND_API_KEY=$${BACKEND_API_KEY:-dev-key} UAI_DATA_ROOT=$${UAI_DATA_ROOT:-/tmp/uai-data} \
	.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

docker:
	docker compose up --build

docker-down:
	docker compose down

backup:
	curl -s -X POST localhost:8000/v1/data/backup -H "X-API-Key: $${BACKEND_API_KEY:-dev-key}" \
	-H 'content-type: application/json' -d '{"label":"make"}' | python3 -m json.tool

audit:
	.venv/bin/python -c "from pathlib import Path; from app import deps_audit; \
r = deps_audit.audit(Path('.'), Path('requirements.txt')); \
print('declared:', r['declared'], '| unused:', len(r['declared_but_not_imported']), \
'| undeclared:', len(r['imported_but_not_declared'])); \
[print('-', note) for note in deps_audit.verdict(r)]"

sdk:
	curl -s "localhost:8000/v1/sdk?lang=python&save_to=client.py" \
	-H "X-API-Key: $${BACKEND_API_KEY:-dev-key}" | python3 -c "import sys,json; d=json.load(sys.stdin); print('wrote', d['saved_to'], d['bytes'], 'bytes')"
