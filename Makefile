PY ?= python3
.PHONY: install test lint check-keys demo up gev smoke
install: ; cd api && pip install -e ".[dev]"
test: ; cd api && pytest -q
lint: ; cd api && ruff check . && mypy app && cd ../workers && ruff check .
check-keys: ; cd api && set -a && [ -f ../.env ] && . ../.env; set +a; $(PY) scripts/check_keys.py
demo: ; cd api && $(PY) -m app.demo && uvicorn app.main:app --port 8000
up: ; docker compose up --build
gev: ; ./console/scripts/setup-gev.sh
smoke: ; NODE_PATH=$$(npm root -g) node console/tests/smoke.spec.cjs
