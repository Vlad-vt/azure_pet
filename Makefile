SHELL := /bin/bash
PY ?= .venv/bin/python
UV ?= uv
export PYTHONPATH := src

.PHONY: help install lint typecheck test test-unit test-integration check up down model data ingest serve eval explain helm-lint bicep-build clean

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-18s %s\n",$$1,$$2}'

install: ## Create venv and install all extras
	$(UV) venv --python 3.12 .venv
	$(UV) pip install -e ".[data,eval,dev]"

lint: ## ruff check + format check
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

typecheck: ## mypy (strict) on src
	$(PY) -m mypy src

test: ## All tests (integration tests skip without SKUMATCH_TEST_DATABASE_URL)
	$(PY) -m pytest

test-unit: ## Unit tests only
	$(PY) -m pytest tests/unit

test-integration: ## Integration tests against pgvector
	$(PY) -m pytest tests/integration

check: lint typecheck test ## Full local quality gate

up: ## Start postgres+pgvector and pgbouncer
	docker compose up -d db pgbouncer

down: ## Stop local stack
	docker compose down

model: ## Download the INT8 ONNX multilingual-e5-small model into ./models
	$(PY) scripts/download_model.py

data: ## Fetch Open Food Facts catalog + generate synthetic invoice benchmark (seed=42)
	$(PY) scripts/fetch_off.py
	$(PY) scripts/generate_synthetic.py
	$(PY) scripts/data_report.py

migrate: ## Apply Alembic migrations
	$(PY) -m alembic upgrade head

ingest: migrate ## Embed + load catalog into Postgres
	$(PY) scripts/ingest.py

serve: ## Run API locally
	$(PY) -m uvicorn skumatch.api.app:app --host 0.0.0.0 --port 8000

eval: ## Benchmark dense vs lexical vs hybrid, log to MLflow, write docs/eval_report.md
	$(PY) scripts/eval.py

explain: ## EXPLAIN ANALYZE the three retrieval queries
	$(PY) scripts/explain.py

helm-lint: ## Lint the Helm chart
	helm lint infra/helm/skumatch
	helm template skumatch infra/helm/skumatch > /dev/null

bicep-build: ## Compile Bicep to ARM (validation)
	az bicep build --file infra/bicep/main.bicep --stdout > /dev/null

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
