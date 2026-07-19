# AI Financial Analyzer — Specification

Production-ready RAG application that ingests financial report PDFs, analyzes them, answers questions about them with citations, and compares reports against each other.

**Design principles:**

- **Everything provider-shaped is configurable.** The LLM, embedding model, vector store, and databases are selected in a config file — no provider names hard-coded in application logic. Default LLM configuration uses **free-tier Gemini** so the app runs at zero model cost; paid providers are a config change.
- **Production-ready.** Multi-user, durable storage, queued background processing, observability, and a defined security posture from day one. See [ARCHITECTURE.md](ARCHITECTURE.md) for the technical architecture.

---

## 1. Overview

**Problem:** Financial reports (10-Ks, 10-Qs, annual reports, earnings releases) are long, dense, and hard to compare across periods or companies. Extracting key metrics, spotting trends, and answering specific questions requires hours of manual reading.

**Solution:** A web application where users upload financial report PDFs into a private library. The system:

1. **Stores** each report durably with extracted metadata (company, period, report type).
2. **Analyzes** each report on ingestion — extracting key financial metrics into structured data and generating a narrative insight summary.
3. **Answers questions** about one or more stored reports using retrieval-augmented generation (RAG), with citations pointing back to the source pages.
4. **Compares** any two or more stored reports — period-over-period for one company, or head-to-head across companies.

**Users:** analysts, finance students, and small teams. Each user has a private document library. v1 is per-user isolation; team/organization sharing is a planned extension (data model reserves space for it).

### Non-goals (v1)

- Real-time market data or stock price integration.
- Investment advice or buy/sell recommendations (insights are descriptive/analytical only).
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

---

## 3. Functional Requirements

### 3.1 Accounts & access control (F0)

- Email + password authentication (Argon2 hashing), JWT access token + rotating refresh token. OAuth (Google) is a fast-follow.
- Every resource (document, chunk, analysis, conversation) is owned by a `user_id`; all queries are scoped server-side — object IDs alone never grant access.
- Per-user quotas, enforced at the API layer and configurable per deployment: max stored documents, max uploads/day, max questions/day.
- Account deletion removes PDFs, chunks, embeddings, provider file references, analyses, and conversations within 24h.

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
  provider: pgvector            # pgvector | chroma | qdrant | faiss
  # pgvector reuses database.url; others take their own connection settings

database:
  url: ${DATABASE_URL}          # any SQLAlchemy URL; Postgres in production

object_storage:
  provider: s3                  # s3 | local
  bucket: reports
  endpoint_env: S3_ENDPOINT     # MinIO locally, S3/R2 in production

queue:
  url: ${REDIS_URL}

chunking: { target_tokens: 800, overlap_tokens: 100 }

limits:
  max_upload_mb: 30
  max_pages: 600
  max_compare_docs: 5
  quotas: { documents: 100, uploads_per_day: 20, questions_per_day: 200 }
```

**Profiles:**

| Profile | LLM / Embeddings | Vector store | DB | Storage | Queue |
|---|---|---|---|---|---|
| `dev` (zero-ops) | Gemini free tier | Chroma (local) | SQLite | local disk | in-process |
| `prod` (default) | Gemini free tier (paid providers opt-in) | **pgvector** | **Postgres** | S3-compatible | Redis + workers |
| `offline` | Ollama + local sentence-transformers | Chroma | SQLite | local disk | in-process |

**Provider interfaces** (contracts application code depends on — full detail in [ARCHITECTURE.md](ARCHITECTURE.md)):

- `LLMProvider` — `generate()` (streaming), `generate_structured(schema)` (Pydantic in/out), `supports_pdf_input` capability flag, `attach_pdf()`.
- `EmbeddingProvider` — `embed_documents()`, `embed_query()`, `dimension`.
- `VectorStore` — `upsert()`, `query(vector, k, filters)`, `delete_by_document()`.

**Rules that make swapping safe:**

- Capability flags, not provider checks — core code asks `llm.supports_pdf_input`, never `if provider == "gemini"`. Providers without native PDF input (most Ollama models) fall back to the parsed-text path automatically.
- Structured output is the adapter's problem — each adapter maps a Pydantic schema to its provider's mechanism (Gemini `response_schema`, OpenAI structured outputs, Anthropic `output_config.format`) and validates before returning.
- Embedding changes invalidate the index — the store records `embedding_model` + `dimension` per collection; a config mismatch at startup is a hard error offering explicit re-indexing, never silent mixing.
- Prompts are provider-neutral; provider-specific tuning (thinking budgets, prompt caching) lives inside adapters as optional optimizations.

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
| `GET` | `/analyses/{id}` | Fetch a stored analysis. |
| `GET` | `/config` | Current non-secret provider config (model attribution in UI). |
| `GET` | `/healthz` · `/readyz` | Liveness / readiness (DB, queue, vector store checks). |

---

## 6. Non-Functional Requirements

### Performance & availability

- Q&A first token < 5s (p95) on hosted providers; API reads < 300ms (p95).
- Ingestion of a 150-page report < 5 min on paid tiers; free-tier throttling surfaces as progress, not failure.
- Target availability 99.5%. API and workers are stateless and horizontally scalable; state lives in Postgres, Redis, and object storage.
- Graceful degradation: if the LLM provider is down, library/search/reading remain available; analysis and Q&A return a clear provider-outage error.

### Correctness

- The model returns `null` / "not found" rather than inventing figures; every extracted number carries `source_page`.
- Comparison arithmetic is computed in code, never by the model.
- A regression eval set (≥ 20 Q&A pairs with expected citations, plus metric-extraction fixtures) runs in CI against a recorded-response provider fake, and on demand against live providers.

### Security & privacy

- Transport: TLS everywhere. At rest: object-storage and DB encryption (provider-level).
- AuthZ: all queries user-scoped server-side; IDs are UUIDs; no cross-tenant access path.
- Uploads validated (magic bytes, size, page count) and never executed; PDFs served back only via short-lived signed URLs.
- Secrets only via environment/secret manager; never logged, never in the DB, never in config files.
- Prompt-injection posture: document content is untrusted input — system prompts instruct the model to treat document text as data; model output is rendered as sanitized Markdown (no raw HTML), and citation markers are validated against supplied chunks.
- Rate limiting per user and per IP at the API layer.
- Reports may be non-public: no third-party analytics; the `offline` profile keeps all data on-machine.

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

---

## 9. Open Questions

1. **Scanned PDFs** — v1 assumes digital PDFs. OCR fallback (vision-capable provider on page images) deferred until needed.
2. **Team workspaces** — schema reserves `user_id` ownership; moving to org-scoped sharing needs a membership/roles model. Post-v1.
3. **XBRL ingestion** — structured filings would make metric extraction near-exact; revisit after P4.
4. **LiteLLM vs hand-written adapters** — decide in P1: LiteLLM covers many providers instantly; hand-written adapters are simpler to debug. The interface contract is identical either way.
5. **Re-indexing UX** — embedding-config changes require re-embedding the library; decide automatic-with-confirmation vs manual admin action.
6. **Billing** — usage table already tracks per-user token cost; whether to expose limits/billing to users is a product decision post-v1.
