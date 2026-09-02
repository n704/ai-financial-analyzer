# AI Financial Analyzer — Specification

Production-ready RAG application that ingests financial report PDFs, analyzes them, answers questions about them with citations, compares reports against each other, and forecasts the price series of the companies they cover using a pretrained time-series foundation model.

**Design principles:**

- **Everything provider-shaped is configurable.** The LLM, embedding model, vector store, forecasting model, market-data source, and databases are selected in a config file — no provider names hard-coded in application logic. Default LLM configuration uses **free-tier Gemini** so the app runs at zero model cost; paid providers are a config change.
- **Production-ready, but starts small.** Multi-user, observability, and a defined security posture from day one. The **initial default runs single-process on SQLite + an in-memory cache/queue with zero external services**; the database and cache/queue/event backends are config choices, so scaling to Postgres + Redis is a config change, not a rewrite. See [ARCHITECTURE.md](ARCHITECTURE.md) for the technical architecture.

---

## 1. Overview

**Problem:** Financial reports (10-Ks, 10-Qs, annual reports, earnings releases) are long, dense, and hard to compare across periods or companies. Extracting key metrics, spotting trends, and answering specific questions requires hours of manual reading.

**Solution:** A web application where users upload financial report PDFs into a private library. The system:

1. **Stores** each report durably with extracted metadata (company, period, report type).
2. **Analyzes** each report on ingestion — extracting key financial metrics into structured data and generating a narrative insight summary.
3. **Answers questions** about one or more stored reports using retrieval-augmented generation (RAG), with citations pointing back to the source pages.
4. **Compares** any two or more stored reports — period-over-period for one company, or head-to-head across companies.
5. **Forecasts** the price series of a report's ticker with [TimesFM](https://github.com/google-research/timesfm), Google Research's pretrained time-series foundation model — returning a *probabilistic* forecast (median path + 10th-90th percentile bands) shipped together with a measured accuracy scorecard against naive baselines.

**Users:** analysts, finance students, and small teams. Each user has a private document library. v1 is per-user isolation; team/organization sharing is a planned extension (data model reserves space for it).

### Non-goals (v1)

- Real-time or intraday market data, order execution, or brokerage integration. Forecasting (F6) works from end-of-day bars fetched on demand — this is not a trading system.
- Investment advice or buy/sell recommendations. Insights are descriptive; forecasts are probabilistic and never leave the server without their uncertainty band and measured error history. Neither is a recommendation.
- Per-ticker model training or fine-tuning — TimesFM is used **zero-shot**, so there is no trained artifact to version, serve, or retrain.
- Organization/team workspaces (single-user libraries in v1; schema is forward-compatible).
- Non-PDF inputs (HTML filings, XBRL) — PDF only in v1.

---

## 2. Core User Flows

| # | Flow | Description |
|---|------|-------------|
| F0 | Account | Sign up (email + password), sign in, sign out, delete account (removes all data). |
| F1 | Upload | User uploads a PDF → system stores it, parses, indexes, auto-detects metadata (company, fiscal period, report type), and runs the initial analysis. Progress is visible throughout. |
| F2 | Library | User browses their reports: status (queued / processing / ready / failed), metadata, past analyses. Can retry failed ingestions and delete reports. |
| F3 | Single-report insights | User opens a report → sees extracted metrics (revenue, net income, margins, EPS, cash flow, debt) and a generated insight summary (trends, risks, notable items), each tied to source pages. |
| F4 | Ask questions | User asks free-form questions ("What drove the margin decline?", "Summarize the risk factors") scoped to one report, several, or their whole library. Answers stream with page-level citations. |
| F5 | Compare | User selects 2–5 reports → system produces a comparison: metric deltas table, growth rates, and a narrative on what changed (guidance, risks, segments). |
| F6 | Forecast | User opens a report (or types a ticker) and picks a horizon → system fetches the end-of-day price history, runs a TimesFM forecast, and returns the median path with 10–90% bands, a rolling-origin backtest scorecard against naive baselines, and an optional narrative linking the forecast window to the report's fundamentals. |

---

## 3. Functional Requirements

### 3.1 Accounts & access control (F0)

- Email + password authentication (Argon2 hashing), JWT access token + rotating refresh token. OAuth (Google) is a fast-follow.
- Every resource (document, chunk, analysis, conversation, forecast) is owned by a `user_id`; all queries are scoped server-side — object IDs alone never grant access. The single exception is the `price_series` cache: public closing prices, identical for every tenant, holding nothing user-identifying (see §7).
- Per-user quotas, enforced at the API layer and configurable per deployment: max stored documents, max uploads/day, max questions/day, max forecasts/day.
- Account deletion removes PDFs, chunks, embeddings, provider file references, analyses, conversations, and forecasts within 24h.

### 3.2 Ingestion (F1)

Per uploaded PDF (validated: PDF magic bytes, ≤ configured size/pages), an ingestion job runs through stages, updating `documents.status` and a per-stage progress field:

1. **Store** — PDF written to object storage (`{user_id}/{doc_id}.pdf`); `documents` row created (`status=queued`).
2. **Metadata detection** — one structured LLM call (first ~10 pages; native PDF if the provider supports it, else extracted text) → `{company, ticker?, report_type (10-K | 10-Q | annual | earnings | other), fiscal_period, currency, fiscal_year_end}`. Presented to the user for confirmation/edit.
3. **Parse & chunk** — per-page text extraction (PyMuPDF); split on detected section headings (MD&A, Risk Factors, Financial Statements, Notes) falling back to page groups; target ~800 tokens per chunk with ~100 overlap; tables extracted (pdfplumber) and serialized as Markdown inside chunks so numbers survive retrieval. Every chunk carries `document_id, company, fiscal_period, report_type, section, page_start, page_end`.
4. **Embed & index** — batch-embed and upsert into the vector store.
5. **Initial analysis** — metric extraction + insight summary (Section 4); `status=ready`.

Failures set `status=failed` with a stored, user-readable error and a retry action. All model calls apply rate-limit-aware backoff; on free-tier providers, ingestion degrades to slower-but-successful rather than failing.

### 3.3 Analysis (F3)

- **Metric extraction (structured):** one structured-output call per document against the `FinancialMetrics` schema (revenue, cost of revenue, gross/operating/net income, diluted EPS, operating/free cash flow, total debt, cash, segment revenues, verbatim guidance, period, prior-period comparatives). Every value nullable — the model must never invent numbers — and every number carries a `source_page`.
- **Insight summary (narrative):** sections — Performance highlights · Trends · Risks & red flags · Notable one-offs · Management outlook. Constraints: descriptive analysis only, every claim tied to a page reference, no investment advice, unverifiable metrics flagged.
- Both stored in `analyses` with the `provider` + `model` that produced them; re-runnable on demand.

### 3.4 RAG Q&A (F4)

1. Embed the question; retrieve top-k (k=8) chunks with metadata filters (`user_id` always; `document_ids` when scoped). Weak retrieval (low similarity) widens k or produces an honest "not found" rather than a thin answer.
2. Retrieved chunks are numbered in the prompt as `[1] (Company FY2025, MD&A, pp. 41–43): <text>`; the model must append `[n]` markers to every claim. This prompt-based citation scheme is provider-neutral.
3. The backend validates markers against the supplied chunks (unknown markers stripped and logged) and renders citation chips linking to the PDF page.
4. Answers stream (SSE); conversations persist for multi-turn follow-ups.
5. Guardrails (system prompt): answer only from provided excerpts; say "not found in the selected reports" when unsupported; never extrapolate numbers; no investment advice.

### 3.5 Comparison (F5)

1. Load stored `FinancialMetrics` per document (re-extract if missing).
2. **Deltas and growth rates computed in Python** — arithmetic is deterministic; the model narrates, it never does the math.
3. Retrieve qualitative chunks per comparison dimension (risk factors, guidance, segments) from each document.
4. One LLM call produces the narrative: what changed, management's stated reasons, divergences between framing and numbers.
5. Output = computed delta table + generated narrative, stored with participating doc IDs.

### 3.6 Market forecasting (F6)

Forecasting is **provider-shaped** like everything else: core code depends on `ForecastProvider` and `MarketDataProvider` and never names a model. The reference adapter wraps **[TimesFM](https://github.com/google-research/timesfm)** (Google Research) — a decoder-only pretrained time-series foundation model that forecasts **zero-shot**: no per-ticker training, no fitted state, no model artifacts to serve.

`POST /forecasts` runs as a **queued job**, never inline — a 200M-parameter torch forward pass is CPU-bound and would stall the API event loop:

1. **Resolve the series.** `ticker` comes from `documents.ticker` (detected in F1) or is supplied directly, validated against `^[A-Z][A-Z0-9.\-]{0,9}$`. The `MarketDataProvider` returns end-of-day OHLCV bars for the window. Price bars are public data, so they are cached globally per `(ticker, interval, as_of)` and shared across users; the *forecast artifact* built from them is `user_id`-owned like every other resource.
2. **Prepare the context.** The trailing `min(max_context, len(series))` closes form the context array. The transform is explicit config (`level | log | log_return`, default `log`) because raw price levels are non-stationary; the transform and its inverse live in `domain/forecast.py` and are unit-tested round-trip.
3. **Forecast.** `ForecastProvider.forecast(contexts, horizon, quantiles)` returns a point path plus 0.1–0.9 quantile paths. Checkpoint loading, `ForecastConfig` compilation, device selection, and batching are the adapter's problem; the model is loaded once per process and kept resident (~1 GB RSS for TimesFM 2.5).
4. **Backtest, in Python.** A rolling-origin backtest over the trailing `backtest_windows` origins scores the selected provider *and* the always-available naive baselines (last-value/drift, seasonal-naive) on MASE, sMAPE, pinball loss, and 80% interval coverage. Computed in `domain/forecast.py` — never by the LLM, the same rule as comparison deltas.
5. **Persist.** Forecast, quantiles, scorecard, provider/model/checkpoint revision, context window, and an `input_hash` land in `forecasts`. Identical inputs against unchanged closing data return the stored artifact instead of re-running inference.
6. **Narrate (optional).** `POST /forecasts/{id}/narrate` hands the *computed* table plus retrieved chunks from the linked report to the LLM for a descriptive narrative — what the report says about drivers over the forecast window, and where the report's framing and the forecast diverge. The model reads numbers; it never produces them.

**Honesty requirements** — functional requirements, not UI polish:

- **Never a bare point estimate.** Median path, 10–90% band, and the backtest scorecard are emitted together, in every response and every view. A provider with no quantile head (capability flag `supports_quantiles=False`) gets empirical intervals derived from its backtest residuals instead — the band is not optional.
- **Skill is measured, not assumed.** Every forecast carries its MASE against seasonal-naive on that same series. Equity closes are close to a random walk, and a foundation model that fails to beat drift on a given ticker must say so — `skill: "no better than naive"` in the payload and on the chart — rather than rendering an authoritative-looking curve. Reporting weak skill honestly is a **passing** outcome; hiding it is a defect.
- **No recommendations.** No buy/sell/hold, no price targets framed as advice, no position sizing. The output is a distribution over a price path with its error history attached, plus a standing disclaimer (versioned in `forecasts.disclaimer_version`).
- **Provenance on every artifact:** data source and `as_of` date, provider, model checkpoint + revision, transform, context window, horizon, and generation time.
- **Forecasts never enter the citation space.** A forecast is a computed artifact, not a document claim; Q&A that references one cites `forecast:{id}`, never a page. Retrieval and forecasting stay separate evidence channels.

---

## 4. Configuration System

A single `config.yaml` (path via `APP_CONFIG`) selects every swappable component. Secrets are never in the file — each provider block names the env var holding its key.

```yaml
llm:
  provider: gemini              # gemini | anthropic | openai | ollama
  model: gemini-2.5-flash       # free tier via Google AI Studio
  api_key_env: GEMINI_API_KEY
  options: { max_output_tokens: 16000 }

embeddings:
  provider: gemini              # gemini | voyage | openai | local
  model: gemini-embedding-001
  api_key_env: GEMINI_API_KEY

vector_store:
  provider: chroma              # chroma | pgvector | qdrant | faiss
  path: ./data/chroma           # pgvector reuses database.url; others take their own settings

database:
  url: sqlite:///./data/app.db  # any SQLAlchemy URL; postgresql+psycopg://... to scale

cache:
  backend: memory               # memory | redis  (rate-limit counters, ephemeral cache)
  # url: ${REDIS_URL}           # required when backend: redis

queue:
  backend: inprocess            # inprocess | arq  (arq needs redis + a separate worker)
  # url: ${REDIS_URL}

events:                         # SSE progress bus
  backend: inprocess            # inprocess | redis
  # url: ${REDIS_URL}

object_storage:
  provider: local               # local | s3
  path: ./data/pdfs             # s3: set `bucket` + `endpoint_env` instead

market_data:
  provider: fixture             # fixture | stooq | yfinance | alphavantage | tiingo
  api_key_env: MARKET_DATA_API_KEY   # omitted by keyless sources (fixture, stooq)
  interval: 1d                  # EOD bars; intraday needs supports_intraday
  max_history_days: 3650
  cache_ttl_s: 900

forecast:
  enabled: false                # opt-in: torch + a 200M checkpoint are not part of the zero-dependency default
  provider: naive               # naive | timesfm | fake
  model: google/timesfm-2.5-200m-pytorch
  revision: main                # pinned checkpoint revision; verified on download
  weights_license_ack: false    # must be true to load non-commercially-licensed weights (TimesFM 3.0)
  device: cpu                   # cpu | cuda | mps
  max_context: 1024             # TimesFM 2.5 supports up to 16k; 1024 keeps CPU latency sane
  max_horizon: 256
  transform: log                # level | log | log_return
  quantiles: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
  backtest_windows: 8
  cache_ttl_s: 3600

chunking: { target_tokens: 800, overlap_tokens: 100 }

limits:
  max_upload_mb: 30
  max_pages: 600
  max_compare_docs: 5
  max_forecast_horizon: 120     # trading days — beyond this the backtest can't support the claim
  quotas: { documents: 100, uploads_per_day: 20, questions_per_day: 200, forecasts_per_day: 50 }
```

**Profiles:**

| Profile | LLM / Embeddings | Vector store | DB | Cache / Queue / Events | Storage | Process model |
|---|---|---|---|---|---|---|
| `dev` **(default / initial)** | Gemini free tier | Chroma (local) | **SQLite** | **in-memory / in-process** | local disk | single process |
| `scaled` (`config/scaled.yaml`) | Gemini free tier (paid opt-in) | pgvector | Postgres | **Redis** | S3-compatible | API replicas + worker |
| `offline` | Ollama + local sentence-transformers | Chroma | SQLite | in-memory / in-process | local disk | single process |

The default profile needs **no external services** — a SQLite file, an in-memory cache/queue, and local disk. `scaled` swaps four backend lines (`database`, `cache`, `queue`, `events`) to Postgres + Redis and adds a separate worker; nothing in application code changes.

**Forecasting per profile.** `dev` and `test` ship `forecast.enabled: false` so the zero-dependency default stays zero-dependency — `timesfm[torch]` plus a 200M-parameter checkpoint is a deliberate opt-in (`uv sync --extra forecast`), and enabling it without the extra fails fast at startup rather than at first request. `scaled` runs `provider: timesfm` with the model resident in the worker. `offline` may enable it as well: TimesFM inference is fully local, so the offline profile keeps its no-network property as long as `market_data.provider` is `fixture` (or a pre-seeded cache) and the checkpoint is pre-downloaded (`HF_HUB_OFFLINE=1`).

**Provider interfaces** (contracts application code depends on — full detail in [ARCHITECTURE.md](ARCHITECTURE.md)):

- `LLMProvider` — `generate()` (streaming), `generate_structured(schema)` (Pydantic in/out), `supports_pdf_input` capability flag, `attach_pdf()`.
- `EmbeddingProvider` — `embed_documents()`, `embed_query()`, `dimension`.
- `VectorStore` — `upsert()`, `query(vector, k, filters)`, `delete_by_document()`.
- `MarketDataProvider` — `fetch_series(ticker, start, end, interval)`, `supports_intraday` capability flag.
- `ForecastProvider` — `forecast(contexts, horizon, quantiles)`, plus `max_context`, `supports_quantiles`, and `supports_covariates` capability flags.

**Rules that make swapping safe:**

- Capability flags, not provider checks — core code asks `llm.supports_pdf_input`, never `if provider == "gemini"`. Providers without native PDF input (most Ollama models) fall back to the parsed-text path automatically.
- Structured output is the adapter's problem — each adapter maps a Pydantic schema to its provider's mechanism (Gemini `response_schema`, OpenAI structured outputs, Anthropic `output_config.format`) and validates before returning.
- Embedding changes invalidate the index — the store records `embedding_model` + `dimension` per collection; a config mismatch at startup is a hard error offering explicit re-indexing, never silent mixing.
- Prompts are provider-neutral; provider-specific tuning (thinking budgets, prompt caching) lives inside adapters as optional optimizations.
- **Infrastructure is a backend, not a fork.** Database (SQLAlchemy URL), cache, queue, and the SSE event bus each sit behind an interface with a default in-memory/in-process implementation and a Redis (and Postgres, for the DB) implementation. Core code depends on `Cache` / `TaskQueue` / `EventBus`, never on `redis`/`arq` directly. Choosing in-memory backends implies a single process; choosing Redis unlocks multiple API replicas + a separate worker.
- **Model weights carry a license gate** — the embedding-space guard's sibling, applied to license terms instead of vector spaces. TimesFM weights up to **2.5 are Apache-2.0** and load freely; **TimesFM 3.0 weights ship under `timesfm-non-commercial-license-v1.0`, restricted to non-commercial, non-production use**. Selecting non-commercially-licensed weights without `forecast.weights_license_ack: true` is a hard startup error, not a warning. 2.5 is the default precisely because this app is meant to run in production.
- **Forecast inference is a job, not a request handler.** Loading and running a 200M-parameter torch model blocks its process, so forecasts go through `TaskQueue` (thread executor in-process by default, arq worker when scaled) and stream progress over the same `EventBus` as ingestion. Capability flags let core code degrade gracefully: no quantile head → empirical intervals from backtest residuals; no covariate support → univariate context only.

---

## 5. API Surface

All endpoints under `/api/v1`, JWT-authenticated except auth endpoints. OpenAPI schema published.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/register` · `/auth/login` · `/auth/refresh` · `/auth/logout` | Account lifecycle. |
| `DELETE` | `/auth/account` | Delete account + all data. |
| `POST` | `/documents` | Upload PDF (multipart). Returns `doc_id`; ingestion is queued. |
| `GET` | `/documents` | List caller's library with status + metadata (paginated). |
| `GET` | `/documents/{id}` | Detail: metadata, analyses, ingestion progress. |
| `PATCH` | `/documents/{id}` | Correct auto-detected metadata. |
| `DELETE` | `/documents/{id}` | Remove PDF, chunks, embeddings, provider file refs, analyses. |
| `POST` | `/documents/{id}/analyze` | (Re)run metrics + insights. |
| `POST` | `/documents/{id}/retry` | Retry failed ingestion. |
| `POST` | `/compare` | `{document_ids: [...], focus?}` → comparison result. |
| `POST` | `/conversations` | Start a Q&A conversation with a document scope. |
| `POST` | `/conversations/{id}/messages` | Ask a question; response streams (SSE). |
| `POST` | `/forecasts` | `{ticker or document_id, horizon, interval?}` → queues a forecast; returns `forecast_id` + SSE progress channel. |
| `GET` | `/forecasts` | List caller's forecasts (filter by ticker or document). |
| `GET` | `/forecasts/{id}` | Forecast artifact: median path, quantile bands, backtest scorecard, skill verdict, provenance, disclaimer. |
| `POST` | `/forecasts/{id}/narrate` | Descriptive narrative tying the computed forecast to the linked report (streams, SSE). |
| `DELETE` | `/forecasts/{id}` | Remove a stored forecast. |
| `GET` | `/analyses/{id}` | Fetch a stored analysis. |
| `GET` | `/config` | Current non-secret provider config (model attribution in UI). |
| `GET` | `/healthz` · `/readyz` | Liveness / readiness (DB, queue, vector store checks). |

---

## 6. Non-Functional Requirements

### Performance & availability

- Q&A first token < 5s (p95) on hosted providers; API reads < 300ms (p95).
- Ingestion of a 150-page report < 5 min on paid tiers; free-tier throttling surfaces as progress, not failure.
- Forecast job < 15s p95 cold (includes checkpoint load) and < 3s p95 warm, for a 1024-point context and a 60-day horizon on CPU. The resident TimesFM 2.5 model costs ~1 GB RSS in whichever process drains the queue — budgeted for, and the reason `forecast.enabled` defaults to `false`.
- Target availability 99.5%. The default single-process profile (SQLite + in-memory) suits small/personal deployments; the `scaled` profile makes the API stateless and horizontally scalable with a separate worker, state living in Postgres, Redis, and object storage. The switch is config-only.
- Graceful degradation: if the LLM provider is down, library/search/reading remain available; analysis and Q&A return a clear provider-outage error.

### Correctness

- The model returns `null` / "not found" rather than inventing figures; every extracted number carries `source_page`.
- Comparison arithmetic is computed in code, never by the model.
- A regression eval set (≥ 20 Q&A pairs with expected citations, plus metric-extraction fixtures) runs in CI against a recorded-response provider fake, and on demand against live providers.
- Forecast arithmetic — transforms and their inverses, returns, MASE/sMAPE/pinball/coverage — is computed in `domain/forecast.py`, never by the LLM, which only narrates a table it is handed read-only.
- A **forecast eval set** (fixture price series with known continuations) runs in CI: every run scores the configured provider against seasonal-naive and drift, and a regression in *relative* skill fails the build. The bar is "measures and reports skill correctly", not "beats the baseline" — on equity closes it frequently will not, and the system is required to say so.

### Security & privacy

- Transport: TLS everywhere. At rest: object-storage and DB encryption (provider-level).
- AuthZ: all queries user-scoped server-side; IDs are UUIDs; no cross-tenant access path.
- Uploads validated (magic bytes, size, page count) and never executed; PDFs served back only via short-lived signed URLs.
- Secrets only via environment/secret manager; never logged, never in the DB, never in config files.
- Prompt-injection posture: document content is untrusted input — system prompts instruct the model to treat document text as data; model output is rendered as sanitized Markdown (no raw HTML), and citation markers are validated against supplied chunks.
- Rate limiting per user and per IP at the API layer.
- Reports may be non-public: no third-party analytics; the `offline` profile keeps all data on-machine.
- Ticker inputs are pattern-validated before reaching any market-data client; market-data fetches are per-user rate-limited and quota'd because they hit third-party APIs and cost money. Price series carry no user content, so the global bar cache leaks nothing across tenants — forecast artifacts remain `user_id`-scoped.
- Model weights are fetched from HuggingFace on first use: pinned by revision, integrity-checked, cached in a mounted volume. Air-gapped deployments pre-seed the cache and run with `HF_HUB_OFFLINE=1`. Weight downloads never happen implicitly inside a request.

### Observability & operations

- Structured JSON logs with request IDs and user IDs (no document content in logs).
- Metrics (Prometheus): request latency, queue depth, ingestion stage durations/failures, provider call latency/error/429 rates, token usage per provider.
- Error tracking (Sentry-compatible). Every LLM call logs provider, model, token counts, and cost estimate to a `usage` table for per-user accounting.
- Migrations via Alembic; deploys are rolling with health-checked containers; DB backed up daily with tested restore. See [ARCHITECTURE.md](ARCHITECTURE.md) §7–8.

---

## 7. Data Model (summary)

Canonical schema and index details in [ARCHITECTURE.md](ARCHITECTURE.md) §5.

```
users            id · email · password_hash · created_at · quota overrides?
documents        id · user_id · filename · storage_key · provider_file_ref?
                 company · ticker? · report_type · fiscal_period · currency
                 page_count · status (queued|processing|ready|failed) · stage · error? · created_at
chunks           id · document_id · section · page_start · page_end · text · token_count · chunk_index
index_meta       embedding_provider · embedding_model · dimension
analyses         id · user_id · type (metrics|insights|comparison) · document_ids[] · result · provider · model · created_at
price_series     ticker · interval · source · as_of · start · end · bars · fetched_at   (global cache; public data, not user-owned)
forecasts        id · user_id · document_id? · ticker · interval · horizon · transform
                 provider · model · checkpoint_revision · context_start · context_end
                 point[] · quantiles[][] · backtest · skill · input_hash · disclaimer_version · created_at
conversations    id · user_id · document_ids[] · created_at
messages         id · conversation_id · role · content · citations · created_at
usage            id · user_id · kind (llm|embedding) · provider · model · tokens_in · tokens_out · cost_estimate · created_at
```

---

## 8. Milestones

| Phase | Scope | Exit criteria |
|---|---|---|
| **P1 — Foundation** | Config loader + profiles, provider interfaces + Gemini adapter, Postgres/Alembic, object storage, auth (register/login/JWT), CI (lint, typecheck, tests vs fake provider) | Swapping `llm.model` in config changes behavior with no code change; authenticated CRUD on an empty library |
| **P2 — Ingest & analyze** | Queued ingestion pipeline with stage progress, metadata detection, parsing/chunking/embedding, metric extraction, insight summary, library UI | Upload a 10-K on free Gemini config → metrics table + insights with page references; failure → visible error + working retry |
| **P3 — RAG Q&A** | Retriever, `[n]`-marker cited Q&A with SSE streaming, conversation history, citation chips linking to PDF pages | 10 varied questions on one report → grounded, cited answers; unanswerable questions refused; eval set green in CI |
| **P4 — Comparison** | Python-computed deltas, comparison narrative, comparison UI | FY2024 vs FY2025 10-K of one company → correct delta table + coherent narrative |
| **P5 — Production hardening** | Second LLM adapter (Anthropic or Ollama) proving the interface, quotas + rate limiting, metrics/dashboards, Sentry, signed URLs, backups + restore drill, load test | Same eval set passes under two provider configs; restore drill documented; p95 targets met under load test |
| **P6 — Market forecasting** | `MarketDataProvider` + `ForecastProvider` interfaces, naive baselines, TimesFM adapter, backtest math in `domain/forecast.py`, queued forecast jobs, forecast chart + narration UI | A ticker on a stored report yields a banded forecast with a backtest scorecard and an honest skill verdict; switching `forecast.provider` between `naive` and `timesfm` is config-only; the forecast eval runs in CI |

---

## 9. Open Questions

1. **Scanned PDFs** — v1 assumes digital PDFs. OCR fallback (vision-capable provider on page images) deferred until needed.
2. **Team workspaces** — schema reserves `user_id` ownership; moving to org-scoped sharing needs a membership/roles model. Post-v1.
3. **XBRL ingestion** — structured filings would make metric extraction near-exact; revisit after P4.
4. **LiteLLM vs hand-written adapters** — decide in P1: LiteLLM covers many providers instantly; hand-written adapters are simpler to debug. The interface contract is identical either way.
5. **Re-indexing UX** — embedding-config changes require re-embedding the library; decide automatic-with-confirmation vs manual admin action.
6. **Billing** — usage table already tracks per-user token cost; whether to expose limits/billing to users is a product decision post-v1.
7. **Default market-data source** — `stooq` is keyless and EOD-only (least friction); `yfinance` is richer but unofficial and rate-limits hard; Alpha Vantage / Tiingo need keys and carry redistribution terms. Decide in P6; the interface makes it swappable, and `fixture` keeps CI hermetic regardless.
8. **TimesFM 3.0 vs 2.5** — 3.0 adds native past-and-future covariate support (the interesting version of this feature: conditioning a price forecast on extracted fundamentals), but its weights are non-commercial and non-production. 2.5 (Apache-2.0, 16k context, quantile head) is therefore the default. Revisit if the 3.0 license changes.
9. **Fundamentals as covariates** — feeding extracted `FinancialMetrics` (quarterly revenue, margins, guidance) in as covariates is the natural bridge between this app's RAG half and its forecasting half. Deferred: it needs the 3.0 licensing question resolved plus careful alignment of quarterly fundamentals onto daily bars (release-date lag, restatements, look-ahead bias).
10. **Horizon cap** — whether to hard-cap the offered horizon at what the rolling-origin backtest can actually support (~60 trading days), or allow longer horizons with a widening band and a louder warning. `limits.max_forecast_horizon` exists either way.
