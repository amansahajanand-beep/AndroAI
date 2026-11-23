.PHONY: help install install-py install-web test api web up down migrate schemas

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

migrate:
	cd apps/api && ../../$(PY) -m alembic upgrade head

schemas:
	$(PY) scripts/export_contract_schemas.py

up:
	docker compose up --build

down:
	docker compose down
