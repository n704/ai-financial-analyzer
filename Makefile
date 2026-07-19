.PHONY: install lint format typecheck test check run worker up up-scaled down

install:        ## Install dependencies (incl. dev group)
	uv sync

lint:           ## Ruff lint
	uv run ruff check .

format:         ## Ruff format
	uv run ruff format .

typecheck:      ## mypy on app/
	uv run mypy app

test:           ## Run pytest
	uv run pytest

check: lint typecheck test  ## Lint + typecheck + test (what CI runs)

run:            ## Run the API locally with reload
	uv run uvicorn app.main:app --reload --port 8000

worker:         ## Run the worker process
	uv run python -m app.worker

up:             ## Bring up the base topology (single-process: SQLite + in-memory)
	docker compose up --build

up-scaled:      ## Bring up the scaled topology (Postgres + Redis + MinIO + worker)
	docker compose -f docker-compose.yml -f docker-compose.scaled.yml up --build

down:           ## Tear down containers (add the scaled file if you used up-scaled)
	docker compose down
