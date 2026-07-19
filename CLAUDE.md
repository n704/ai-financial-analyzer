# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project State

This is a **greenfield project — no code exists yet**. The repository contains only `SPEC.md`, a complete specification for the application. Read `SPEC.md` before implementing anything; it is the source of truth for architecture, data model, API endpoints, and milestones. There are no build/test/lint commands yet — establish them as the codebase takes shape and record them here.

## What This Project Is

A single-tenant RAG web app: users upload financial report PDFs (10-Ks, 10-Qs, earnings releases), the system extracts metrics and generates insight summaries on ingestion, answers questions with page-level citations, and compares reports (period-over-period or cross-company).

Planned stack (SPEC.md §4): Python 3.12 + FastAPI, Claude Opus 4.8 (`claude-opus-4-8`) via the `anthropic` SDK, Voyage AI `voyage-finance-2` embeddings, Chroma (persistent local) vector store, SQLite via SQLModel, PyMuPDF/pdfplumber for parsing, Jinja2 + htmx frontend, FastAPI `BackgroundTasks` for async ingestion.

## Architecture (planned)

Two parallel paths for PDF understanding, by design:

- **Native PDF path** — each PDF is uploaded once to the Anthropic Files API at ingestion; the stored `file_id` is reused for metadata detection, metric extraction, and insight summaries. Claude reads pages visually, which beats text-scrape quality for table/chart-heavy reports.
- **RAG path** — PyMuPDF extracts per-page text locally; chunks (~800 tokens, ~100 overlap, split on section headings like MD&A/Risk Factors) are embedded with Voyage and indexed in Chroma for Q&A retrieval. Tables are serialized as Markdown inside chunks so numbers survive retrieval.

Ingestion is a staged async pipeline (store → Files API upload → metadata detection → parse/chunk → embed/index → initial analysis), with `documents.status` updated per stage and retry on failure (SPEC.md §5).

## Key Constraints From the Spec

These are deliberate decisions — don't deviate without flagging it:

- **Q&A and metric extraction are separate call shapes on purpose**: citations (`citations: {"enabled": true}`) are incompatible with structured outputs (returns 400). Q&A uses cited free-text over retrieved chunks; metric extraction uses `client.messages.parse()` with Pydantic models and a `source_page` field per value instead.
- **Claude Opus 4.8 API specifics**: use `thinking={"type": "adaptive"}`; do **not** pass `budget_tokens`, `temperature`, `top_p`, or `top_k` (removed on Opus 4.8 — API returns 400). All generation streams (`messages.stream`).
- **Never let the model do arithmetic for comparisons**: deltas and growth rates are computed in Python; the model only narrates (SPEC.md §6.3).
- **Correctness over coverage**: every extracted metric is nullable and carries a `source_page`; the model must return `null`/"not found" rather than invent figures. Q&A answers only from retrieved excerpts and refuses when retrieval doesn't support an answer. No investment advice anywhere — analysis is descriptive only.
- **Prompt caching layout**: system prompts are frozen strings with `cache_control` on the last system block; volatile content (question, chunks) comes after. This layout is what keeps the per-report cost envelope (~$2/ingestion) viable.
- **Files API limits** enforced client-side: ≤32 MB, ≤600 pages per PDF; beta header `files-api-2025-04-14` on upload and message calls.
- **Config**: `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` from environment only; model IDs and chunking parameters centralized in `settings.py`.

## Milestones

Build in order (SPEC.md §12): P1 ingest & analyze → P2 RAG Q&A → P3 comparison → P4 polish/evals. Each phase has explicit exit criteria in the spec.
