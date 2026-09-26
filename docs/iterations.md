# Iteration log

One entry per iteration, newest first. Format: date · milestone · what changed · how it was validated · numbers · next.

## 2026-09-25 · Phase 1 · 1.1 Database and schema

- **What:** `docker-compose.yml` (pgvector/pgvector:pg18, localhost:5432, healthcheck), idempotent `db/schema.sql` (documents, sections, chunks, users, answers; HNSW halfvec(1536), GIN tsv, trigram, btree indexes; generated `tsv`), `Makefile` (`up`, `db`, `test`, `psql`), `tests/test_schema.py`. Deps: psycopg[binary], pgvector, pytest (dev). Tables for citations, glossary, guides, synonyms, ingest_jobs deferred to the iterations that use them.
- **Validated:** tests red first (13 failed, 1 passed on empty schema) → green (14 passed, 0.25 s). `docker compose ps` → healthy; `make db` twice → exit 0, no notices; `\d chunks` shows `embedding halfvec(1536)` and generated `tsv`; vector 0.8.6, pg_trgm 1.6.
- **Numbers:** 14 tests; DB healthy in < 5 s.
- **Next:** 1.2 — approval table for the A2AJ Ontario statute files, then download, manifest and match report.

## 2026-09-25 · Phase 0 · Vertex AI access

- **What:** `scripts/check_vertex.py` smoke-tests every model call the design depends on, via ADC.
- **Validated:** `uv run scripts/check_vertex.py` → 6/6 pass (3.7 Flash, 3.5 Flash-Lite, gemini-embedding-2 at 1536 dims, structured claims with quote verification, Google Search grounding, Flash-Lite listwise rerank ranked the right passage first).
- **Numbers:** 3.7 Flash 1–3 s per call at low thinking; 3.8 Flash timed out on most calls; grounding with default thinking took 87 s then 504.
- **Next:** Phase 1 — Docker Compose with Postgres 18 + pgvector, schema, and loading the v0 Ontario statutes from A2AJ.
