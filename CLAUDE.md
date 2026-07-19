# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project State

**P0 (bootstrap) and P1 (foundation) are complete.** Config system (fail-fast validation, env-var secret resolution, dev/scaled/offline/test profiles); provider protocols with fake + Gemini adapters (contract-tested) and Chroma/pgvector vector stores behind the embedding-space startup guard; `Cache`/`TaskQueue`/`EventBus` with in-memory + Redis backends; local/S3 object storage with signed URLs; SQLite/Postgres-portable DB models + Alembic migrations + user-scoped repositories; full auth cycle (register/login/rotating refresh/logout/delete-account); a FastAPI app wiring all of it together with request-id logging and per-IP/per-user rate limiting. No product behavior yet (no documents, no Q&A) — that starts at P2. Feature work follows the phased plan.

Read these before implementing, in order: **[SPEC.md](SPEC.md)** (what — requirements, config system, API, data model), **[ARCHITECTURE.md](ARCHITECTURE.md)** (how — services, provider abstraction, flows), **[PLAN.md](PLAN.md)** (build order — P0–P5 with per-task exit criteria). They are the source of truth; keep them in sync when decisions change.

## What This Project Is

A **production-ready, multi-user** RAG web app: users upload financial report PDFs (10-Ks, 10-Qs, earnings releases); the system extracts metrics and generates insight summaries on ingestion, answers questions with page-level citations, and compares reports (period-over-period or cross-company).

**Design axis #1 — everything provider- and infra-shaped is configurable.** The LLM, embedding model, vector store, database, cache, queue, and SSE event bus are all chosen in `config.yaml`; application code depends only on interfaces (`LLMProvider` / `EmbeddingProvider` / `VectorStore` / `Cache` / `TaskQueue` / `EventBus`). The **default is zero-dependency**: free-tier Gemini (`gemini-2.5-flash` + `gemini-embedding-001`), **SQLite**, **in-memory cache/queue/events**, local-disk storage — the whole app runs single-process with no external services (`config/dev.yaml`). Scaling to Postgres + Redis + a separate worker is `config/scaled.yaml` — a config change, not a code change. Never hard-code a provider or backend name in core code — see the constraints below.

## Commands

```bash
make install     # uv sync (deps + dev group)
make check       # lint + typecheck + test  ← run before every commit
make lint        # ruff check .
make format      # ruff format .
make typecheck   # mypy app
make test        # pytest
make run         # uvicorn app.main:app --reload  (API on :8000)
make worker      # python -m app.worker
make up          # base topology (single-process: SQLite + in-memory)
make up-scaled   # scaled topology (Postgres + Redis + MinIO + worker)
make down        # tear down containers
```

Toolchain: Python 3.12, uv, ruff (lint+format), mypy (`strict`, extra-strict on `app.domain.*`), pytest. CI runs the same `check` steps.

## Architecture (see ARCHITECTURE.md for detail)

- **Two run modes, one image:** *single-process (default)* — `app.main:app` serves HTTP and runs ingestion jobs in-process (in-memory queue), on SQLite + local disk, no external services. *Scaled* — API replicas + a separate `app.worker` (arq), backed by Redis + Postgres. The split is config (`queue`/`cache`/`events`/`database` backends), not code. Entry selected by `docker/entrypoint.sh`.
- **Layering / dependency rule:** `api`/`services` → `domain` + the `providers`/`infra` interfaces. **Only `app/providers/*` and `app/infra/*` import vendor SDKs** (Gemini, `redis`, `arq`, `boto3`, `psycopg`). `app/domain/` is pure, I/O-free, heavily unit-tested (chunking, delta math, citation parsing, schemas).
- **Two PDF paths by design:** native-PDF (providers with `supports_pdf_input=True` read pages visually for analysis) and RAG (PyMuPDF text → chunked → embedded → retrieved for Q&A).

## Key Constraints From the Spec

Deliberate decisions — don't deviate without flagging it:

- **Configurability over provider checks.** Ask capability flags (`llm.supports_pdf_input`), never `if provider == "gemini"`. Structured-output mechanics, rate-limit backoff, and provider-specific tuning live *inside adapters*; prompts and core logic are provider-neutral.
- **Citations are prompt-based `[n]` markers**, validated server-side against the supplied chunks — this works on every provider (incl. local models). Native citation APIs are an optional internal adapter upgrade, not the contract.
- **Never let the model do arithmetic for comparisons** — deltas and growth rates are computed in Python (`app/domain/`); the model only narrates.
- **Correctness over coverage** — every extracted metric is nullable and carries a `source_page`; the model returns `null`/"not found" rather than inventing figures. Q&A answers only from retrieved excerpts and refuses when unsupported. No investment advice — analysis is descriptive only.
- **Embedding-space guard** — `index_meta` records `(embedding_provider, embedding_model, dimension)`; a config mismatch at startup is a hard error requiring an explicit re-index, never silent mixing.
- **Infrastructure is a configurable backend, not a fork** — DB (SQLAlchemy URL), `Cache`, `TaskQueue`, and `EventBus` each have an in-memory/in-process default and a Redis (Postgres for the DB) option. Default = SQLite + in-memory, single process; `config/scaled.yaml` = Postgres + Redis + separate worker. In-memory backends imply one process (their state is per-process). Vector store defaults to Chroma on SQLite, pgvector when on Postgres. Never import `redis`/`arq`/`boto3`/`psycopg` outside `app/infra/*` (and storage/db adapters).
- **Multi-user isolation** — every resource is `user_id`-owned and scoped server-side; there is no load-by-ID-without-ownership path.
- **Secrets** — only via environment; config names the env var, never the value. Never logged, never in the DB.

## When touching an Anthropic adapter

If you implement `app/providers/llm/anthropic.py`: use `claude-opus-4-8`, `thinking={"type": "adaptive"}`, streaming (`messages.stream`); do **not** pass `budget_tokens`/`temperature`/`top_p`/`top_k` (removed on Opus 4.8 — 400). Files API for native PDF (beta `files-api-2025-04-14`); `client.messages.parse()` for structured output. These specifics stay *inside the adapter* — core code never sees them.

## Milestones

Build in order (PLAN.md): **P0 bootstrap ✅ → P1 config/providers/auth → P2 ingest & analyze → P3 RAG Q&A → P4 comparison → P5 hardening.** Each task has an explicit "done when" check in PLAN.md.
