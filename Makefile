.PHONY: install lint format typecheck test check run worker migrate migrate-down up up-scaled down

# Extras beyond the zero-ops default install: gemini (real LLM/embeddings),
# postgres (pgvector adapter), redis (arq queue + Redis cache/events), storage
# (S3/MinIO), parse (PyMuPDF/pdfplumber, lands with P2 chunking). `make install`
# pulls all of them so lint/typecheck/test exercise every adapter, matching CI.
EXTRAS := --extra gemini --extra postgres --extra redis --extra storage --extra parse

install:        ## Install dependencies (incl. dev group + all provider/infra extras)
	uv sync $(EXTRAS)

lint:           ## Ruff lint
	uv run ruff check .

format:         ## Ruff format
	uv run ruff format .

typecheck:      ## mypy on app/
	uv run mypy app

test:           ## Run pytest (fake provider, SQLite, in-memory — no external services)
	uv run pytest

check: lint typecheck test  ## Lint + typecheck + test (what CI runs)

run:            ## Run the API locally with reload
	uv run uvicorn app.main:app --reload --port 8000

worker:         ## Run the worker process
	uv run python -m app.worker

migrate:        ## Apply Alembic migrations to the configured database (APP_CONFIG)
	uv run alembic upgrade head

migrate-down:   ## Roll back one migration
	uv run alembic downgrade -1

up:             ## Bring up the base topology (single-process: SQLite + in-memory)
	docker compose up --build

up-scaled:      ## Bring up the scaled topology (Postgres + Redis + MinIO + worker)
	docker compose -f docker-compose.yml -f docker-compose.scaled.yml up --build

down:           ## Tear down containers (add the scaled file if you used up-scaled)
	docker compose down
