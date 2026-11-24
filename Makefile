.PHONY: help install install-py install-web test api web up down migrate schemas dev-api dev-web dev-worker smoke

PY ?= .venv/bin/python
ifeq ($(OS),Windows_NT)
PY = .venv/Scripts/python
endif

help:
	@echo "install  - create .venv, install all Python packages and web deps"
	@echo "api      - run API on :8000 (needs .env)"
	@echo "web      - run web on :3000"
	@echo "test     - run Python tests"
	@echo "migrate  - alembic upgrade head"
	@echo "schemas  - export JSON Schema from contracts"
	@echo "up/down  - docker compose up --build / down"
	@echo "dev-api  - DEV ONLY: API on SQLite+local storage (no Postgres/Redis), http://localhost:8000"
	@echo "dev-web  - web on :3000 proxying /api to :8000"
	@echo "dev-worker - DEV ONLY fake build worker (WORKER_TOKEN=wk_...); runs no Gradle"
	@echo "smoke    - end-to-end check through the web proxy (needs dev-api + dev-web)"

install: install-py install-web

install-py:
	python -m venv .venv
	$(PY) -m pip install -e "packages/contracts[dev]" -e packages/storage -e packages/android-tools -e "apps/api[dev]" \
		-e workers/orchestration -e workers/ai-agent -e workers/android-build -e workers/android-test

install-web:
	cd apps/web && npm install

api:
	cd apps/api && ../../$(PY) -m uvicorn androai_api.main:app --reload --port 8000

web:
	cd apps/web && npm run dev

test:
	$(PY) -m pytest packages/contracts packages/storage packages/android-tools apps/api
	cd apps/web && npm test

migrate:
	cd apps/api && ../../$(PY) -m alembic upgrade head

schemas:
	$(PY) scripts/export_contract_schemas.py

up:
	docker compose up --build

down:
	docker compose down

dev-api:
	$(PY) scripts/dev/run_api_sqlite.py

dev-web:
	cd apps/web && BACKEND_URL=http://localhost:8000 npm run dev

dev-worker:
	$(PY) scripts/dev/fake_worker.py

smoke:
	$(PY) scripts/dev/smoke_web_api.py
