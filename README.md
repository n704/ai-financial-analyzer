# ai-financial-analyzer

Production-ready RAG application that ingests financial report PDFs (10-Ks, 10-Qs, earnings releases), extracts metrics and generates insight summaries on ingestion, answers questions with page-level citations, and compares reports period-over-period or across companies.

**Configurable by design** — the LLM, embeddings, vector store, database, cache, and queue are all selected in config. The default runs with **zero external services**: free-tier Gemini, SQLite, an in-memory cache/queue, and local-disk storage, all in one process. Scaling to Postgres + Redis + a separate worker is a config swap (`config/scaled.yaml`), not a code change.

## Documentation

| Doc | What it covers |
|---|---|
| [SPEC.md](SPEC.md) | What the system does — requirements, config system, API, data model, milestones |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How it's built — services, provider abstraction, request flows, deployment |
| [PLAN.md](PLAN.md) | Build order — phased tasks (P0–P5) with dependencies and exit criteria |

## Quickstart

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                 # install deps (incl. dev group)
cp .env.example .env     # then add your GEMINI_API_KEY
make check               # lint + typecheck + test
make run                 # API at http://localhost:8000  (docs at /docs)
```

Health check:

```bash
curl localhost:8000/healthz   # {"status":"ok"}
```

### Containers

```bash
make up          # base: single API container (SQLite + in-memory + local volume)
make up-scaled   # scaled: adds Postgres (pgvector) + Redis + MinIO + a worker
make down
```

The default (`make run` or `make up`) needs no external services. `make up-scaled` layers
`docker-compose.scaled.yml` on top and points the app at `config/scaled.yaml`.

## Common commands

| Command | Does |
|---|---|
| `make install` | `uv sync` |
| `make check` | lint + typecheck + test (what CI runs) |
| `make lint` / `make format` | ruff check / ruff format |
| `make typecheck` | mypy on `app/` |
| `make test` | pytest |
| `make run` / `make worker` | run the API / worker locally |
| `make up` / `make down` | docker compose up/down |

## Project layout

```
app/
  main.py          FastAPI app factory (ops endpoints)
  worker.py        worker entrypoint
  config/          config.yaml loading + profiles          (P1.1)
  providers/       LLM / embeddings / vector-store adapters (P1.2+)
  infra/           cache / queue / event-bus backends       (P1.10)
  domain/          pure logic: chunking, deltas, citations  (P2+)
  services/        ingestion, analysis, qa, comparison      (P2+)
  api/ db/ storage/ ui/                                     (P1+)
config/            profile files: dev.yaml (default) + scaled.yaml
docker/            entrypoint + Caddyfile
tests/             unit / integration / evals
```

## Status

**P0 (bootstrap) complete** — package scaffold, tooling (ruff/mypy/pytest), CI, Docker topology, and dev ergonomics are in place; the app and worker boot. See [PLAN.md](PLAN.md) for what's next (P1: config, providers, auth).
