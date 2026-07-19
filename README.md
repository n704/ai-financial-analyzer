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
make install              # uv sync + all provider/infra extras (matches CI)
cp .env.example .env      # then set GEMINI_API_KEY, JWT_SECRET, OBJECT_STORAGE_SIGNING_SECRET
make check                # lint + typecheck + test (fake provider, SQLite, in-memory)
make run                  # API at http://localhost:8000  (docs at /docs)
```

The default profile (`config/dev.yaml`) auto-applies its SQLite migrations on
first boot — no separate release step needed. `JWT_SECRET` and
`OBJECT_STORAGE_SIGNING_SECRET` just need to be *some* long random string for
local dev; `GEMINI_API_KEY` comes from [Google AI Studio](https://aistudio.google.com/)
(free tier).

Try the auth flow once it's running:

```bash
curl localhost:8000/healthz   # {"status":"ok"}

curl -X POST localhost:8000/api/v1/auth/register \
  -H 'content-type: application/json' \
  -d '{"email": "you@example.com", "password": "a-decent-password"}'
# -> {"access_token": "...", "refresh_token": "...", "token_type": "bearer"}

curl localhost:8000/api/v1/auth/me -H "authorization: Bearer <access_token>"
```

### Containers

```bash
make up          # base: single API container (SQLite + in-memory + local volume)
make up-scaled   # scaled: adds Postgres (pgvector) + Redis + MinIO + a worker
make down
```

The default (`make run` or `make up`) needs no external services. `make up-scaled` layers
`docker-compose.scaled.yml` on top and points the app at `config/scaled.yaml` — Postgres
is migrated as an explicit release step there (`make migrate`), not auto-applied like SQLite.

## Common commands

| Command | Does |
|---|---|
| `make install` | `uv sync` + provider/infra extras (gemini, postgres, redis, storage, parse) |
| `make check` | lint + typecheck + test (what CI runs) |
| `make lint` / `make format` | ruff check / ruff format |
| `make typecheck` | mypy on `app/` |
| `make test` | pytest — fake LLM/embeddings, SQLite, in-memory cache/queue/events |
| `make run` / `make worker` | run the API / worker locally |
| `make migrate` / `make migrate-down` | apply / roll back one Alembic migration |
| `make up` / `make down` | docker compose up/down |

## Project layout

```
app/
  main.py          FastAPI app factory: wires config -> DB -> providers -> infra -> storage -> auth
  worker.py        worker entrypoint (arq job loop lands in P2.1)
  config/          config.yaml loading, profiles, secret-env resolution      (P1.1)
  providers/       LLM / embedding / vector-store protocols + adapters + factory
                     llm/, embeddings/: fake (P1.4) + gemini (P1.5/1.6)
                     vectorstores/: chroma (P1.9, default) + pgvector (scaled)
  infra/           Cache / TaskQueue / EventBus: in-memory (default) + Redis   (P1.10)
  db/              SQLAlchemy models, Alembic migrations, user-scoped repos    (P1.8)
  storage/         object storage: local (signed tokens) + s3                 (P1.11)
  api/             auth (service + router), dependencies, middleware, ops     (P1.12/13)
  domain/          pure logic: chunking, deltas, citations                    (P2+)
  services/        ingestion, analysis, qa, comparison                        (P2+)
  ui/                                                                          (P2+)
config/            dev.yaml (default) · scaled.yaml · offline.yaml · test.yaml
docker/            entrypoint + Caddyfile
tests/
  unit/            domain logic, config, providers, infra, DB, auth, the assembled app
  contract/        one suite per provider protocol, run against fake + (if keyed) gemini
  integration/ evals/
```

## Status

**P1 (foundation) complete** — config system with fail-fast validation and
env-var secret resolution; `LLMProvider`/`EmbeddingProvider`/`VectorStore`
protocols with fake + Gemini adapters (contract-tested) and Chroma/pgvector
vector stores with the embedding-space startup guard; `Cache`/`TaskQueue`/
`EventBus` with in-memory + Redis backends; local/S3 object storage with
signed URLs; SQLite/Postgres-portable models + Alembic migrations and
user-scoped repositories; full auth cycle (register/login/rotating
refresh/logout/delete-account) behind Argon2id + JWT; a FastAPI app wiring all
of it together with request-id logging and per-IP/per-user rate limiting.
Swapping `llm.provider`/`model` or the `database`/`cache`/`queue`/`events`
backends is a config change, not a code change. See [PLAN.md](PLAN.md) for
what's next (P2: ingestion pipeline, metric extraction, insight summaries).
