# Iteration log

One entry per iteration, newest first. Format: date · milestone · what changed · how it was validated · numbers · next.

## 2026-09-25 · Phase 1 · 1.9 Review workflow API

- **What:** seeded users "Demo Researcher" / "Demo Reviewer" (schema, idempotent); role from the `X-Demo-User` header (demo only, default researcher, unknown → 422). `app/review.py` + routes: `GET /review/queue` (reviewer only; risky first — refusals, dropped claims, retries — then oldest), `POST /answers/{id}/review` (approve; edit needs `final_markdown` + note; reject needs a reason from wrong_law | missing_authority | unsupported_claim | out_of_scope; one atomic `UPDATE … WHERE status = 'pending_review'`, else 409 or 404), `GET /answers/{id}` (researcher: sources + "Awaiting review" while pending, final text + claims + "reviewed by" after approval, reason after rejection; reviewer: everything). The draft is never overwritten; edits go to `final_markdown`. `/ask` now records `asked_by`.
- **Validated:** tests red first (13/14 failing) → 14 review tests, 156 total. curl walkthrough on the real API: ask "neighbour's dog bit me in Toronto — who is liable?" → researcher view `Awaiting review` with 8 sources and no draft; researcher → queue 403; reviewer queue lists the BC refusal first (risk `out_of_scope`); draft cites Dog Owners' Liability Act s. 2 with 3/3 verified quotes; approve → `approved`; approve again → 409 `conflict`; researcher view → final text, "Demo Reviewer", 3 claims.
- **Numbers:** the first reviewed answer with verified quotes exists (answer 4) — Phase 1 exit half 2 is met at the API level.
- **Next:** 1.10 — Ask and Review pages + browser flow.

## 2026-09-25 · Phase 1 · 1.8 `POST /ask` drafts

- **What:** `app/ask.py`: keyword (terms OR'ed, `ts_rank_cd`) + vector top 50 each, RRF (k = 60), top 8; grounding gate on best cosine distance (`GATE_MAX_DISTANCE = 0.35`, no model call above it); gemini-3.7-flash (low thinking, JSON schema) returns `in_scope`, `answer`, `claims[{text, chunk_id, quote}]`; code keeps a claim only if its chunk was retrieved and its quote (≥ 12 chars) is a substring after normalizing whitespace and curly → straight quotes; zero verified → one retry with feedback → `unverified` refusal. Draft markdown is composed in code (answer + "What the law says" quotes with McGill citations). `POST /ask` returns sources + answer id + `pending_review` only; the draft, claims, dropped claims, sources, distances and timings are stored on `answers`.
- **Validated:** tests red first → 15 unit + 4 endpoint tests (142 total). Real Vertex, 3 questions: (1) "How long do I have to sue after an injury in Ontario?" → drafted, 2 verified quotes (LA s. 15, OLA s. 6.1), but the answer says the general period was not in the passages; (2) "icy sidewalk in Toronto … who, how soon?" → drafted, 3/3 verified: COTA s. 42 (clerk, 10 days) + OLA s. 6.1 (occupier/contractor, 60 days) — correct; (3) "appeal a speeding ticket in BC" → `out_of_scope` (model; best distance 0.299 passed the gate).
- **Numbers:** sources 317–1,117 ms (first call cold), total 2.1–4.5 s (targets < 2 s / < 8 s). 0 dropped claims across 5 verified. Best distances: in scope 0.189–0.251, out of scope 0.299.
- **Baseline gap (for Phase 2/3):** Limitations Act s. 4 is vector rank 4 but absent from keyword results ("sue" ≠ "proceeding"/"claim"), so RRF pushes it out of the top 8 → the design's synonym expansion and reranker; measure with the gold set.
- **Next:** 1.9 — review workflow API (seeded users, queue, approve/edit/reject).

## 2026-09-25 · Phase 1 · 1.7 Law library frontend

- **What:** Next.js 16.3.6 (App Router, TS, Tailwind 4) in `web/`: `/laws` (grouped library with citations, section counts, as-of dates), `/laws/[slug]` (Part → section tree), `/laws/[slug]/[pinpoint]` (official text with legislative hanging indents, breadcrumb, source line "Unofficial copy … as of … · Source … · Official version", McGill copy-citation button, prev/next; excerpt-only notice + toronto.ca link for City chapters), not-found and error pages, skip link, print styles. Design-doc palette as light/dark tokens; Source Serif 4 / Sans 3 / Code Pro via `next/font` (self-hosted). API gained `lines` (indent levels) and `citation` (McGill) from `app/format.py`. Bylaw parser v2 rejoins PDF-wrapped lines into paragraphs (found in the browser: excerpt showed broken lines).
- **Validated:** tests red first where logic lives (format helpers written with their tests; API field test red → green; paragraph test red → green) → 123 passed; `tsc --noEmit` clean. Crawl through Next.js: **3,282/3,282 section pages 200**, p50 28 ms, p95 42 ms (dev server); `/`, `/laws`, a law page 200; unknown law/section 404. Browser: s. 15 hanging indents correct in dark and light; § 719-2 shows paragraphs, excerpt notice and link. Contrast: 16/16 text-on-background pairs ≥ 4.5:1 (min 6.83) in both themes. Keyboard: Tab → visible "Skip to content" with focus ring; one h1, header/main/footer, labelled navs, `lang=en`. Copy button: in a background tab the clipboard is blocked and the fallback message shows; a successful copy was not verified.
- **Numbers:** Toronto re-parse re-embedded 186 chunks in 8.7 s (3,447 chunks total).
- **Not done:** Lighthouse/axe run (would need a new tool download) — Lighthouse CI is on the Phase 4 engineering bar.
- **Next:** 1.8 — `POST /ask` drafts (hybrid retrieval, RRF, grounding gate, verified quotes).

## 2026-09-25 · Phase 1 · 1.6 Law library API

- **What:** FastAPI app (`app/main.py`, queries in `app/laws.py`): `GET /laws` (grouped by kind, section counts), `GET /laws/{slug}` (document + part/section tree, no text), `GET /laws/{slug}/{pinpoint}` (text, children, breadcrumb, prev/next, document provenance). One envelope `{data, error, meta}` for every response, including 404, 422 (slug/pinpoint must match `^[a-z0-9][a-z0-9.\-]*$`) and 500 (logged, generic message). `reproduction='excerpt'` documents return at most 300 chars + "…" and `full_text: false`. Deps: fastapi, uvicorn, httpx (dev). `make api`, `.claude/launch.json` (api), `scripts/crawl_api.py`.
- **Validated:** tests red first → 11 API tests, 108 total passing. Crawl against the running API: 15 laws, **3,282/3,282 section pages 200**, p50 9.5 ms, p95 14.0 ms (target < 100 ms). § 719-2 returns a 301-char excerpt with `full_text: false`; unknown pinpoint → 404.
- **Numbers:** p95 14 ms with a new DB connection per request (no pool yet).
- **Next:** 1.7 — Next.js law library + section pages.

## 2026-09-25 · Phase 1 · 1.5 Toronto Municipal Code layer

- **What:** a research subagent found the chapters (ch. 719 Snow and Ice Removal, 743 Streets and Sidewalks, 629 Property Standards), robots.txt (allowed) and toronto.ca's copyright notice (no copying without permission). User chose: download for local indexing only; UI shows excerpts + link. `scripts/fetch_toronto.py` (≤ 1 req/s, Last-Modified skip, manifest lines with the licence note); `ingest/bylaws.py` parses `pdftotext` output (skips the TOC, drops page headers/numbers/dates, Articles → parts, `§ 743-9` → pinpoint `743-9`); `scripts/load_toronto.py`; new `documents.reproduction` ('full' | 'excerpt').
- **Validated:** tests red first → 97 passed. Fetch 2.56 MB, 3 manifest lines; rerun 0 MB. Load: 719 → 9, 743 → 59, 629 → 58 sections, each equal to the chapter's own TOC; rerun unchanged. Embed: 187 new chunks, 187 calls, 8.8 s; statutes untouched (0 calls). § 719-2 stored text matches the PDF text (whitespace-normalized). Search: "clear snow from the sidewalk in Toronto" → § 719-2 #1; "icy sidewalk … who do I notify" → COTA s. 42 #1 then § 719-2.
- **Numbers:** 15 documents, 3,446 chunks. City of Toronto Act s. 42(6) confirmed locally: written notice to the clerk within 10 days.
- **Next:** 1.6 — law library API (FastAPI).

## 2026-09-25 · Phase 1 · 1.4 Chunk, index, embed

- **What:** `ingest/chunks.py`: one chunk per section; sections over 3,200 chars (~800 tokens) split at subsection boundaries (else at line boundaries), packed greedily; parts and `[blank]` placeholders skipped. Each chunk keeps its section text verbatim, `section_ids`, a first pinpoint, and a deterministic `context` ("Limitations Act, 2002 — s. 4 — Basic limitation period") that feeds `tsv` and the embedding input. `sync_chunks` replaces a document's chunks only when the (pinpoint, hash) list changes and reuses embeddings by hash; `embed_pending` embeds missing/other-model chunks with an 8-thread pool, committing every 25. `ingest/vertex.py` is the shared client (30 s timeout, 5 attempts on 429/5xx). `scripts/embed_chunks.py` runs it all.
- **Validated:** tests red first → 90 passed. Real run: 3,259 chunks, 3,259 calls, 0 missing, 122 s. Rerun: 0 calls (0.9 s). Nulled 10 embeddings → rerun made exactly 10 calls. 0 sections without a chunk. Keyword `limitation period` → Limitations Act chunks only. Vector (RETRIEVAL_QUERY): "time limit to sue" → Limitations Act s. 15, 16(1), **s. 4** (#3); "icy sidewalk in Toronto" → **City of Toronto Act s. 42** #1; "dog bit me" → **Dog Owners' Liability Act s. 2** #1.
- **Numbers:** ~955k tokens embedded once. 25 chunks exceed 3,200 chars (single long lines; max 17,920 chars ≈ 4.5k tokens, under the 8,192-token input limit).
- **Next:** 1.5 — Toronto Municipal Code layer (research + approval table before any download).

## 2026-09-25 · Phase 1 · 1.3 Load statutes into Postgres

- **What:** `ingest/statutes.py` parses each A2AJ row into a document + tree: Part (`##` headings; `### RULE n` for the Rules) > section (A2AJ section map, text kept byte-for-byte) > subsection (`(1)`, `(1.1)` lines; clauses stay inside). Pinpoints `s-4`, `s-4-1`, `r-1.06`, `ss-25-49`, `part-iii.1`, `rule-2.1`, `schedule`; `display_pinpoint` gives `s. 4(1)`. `load_document` inserts/replaces one document per transaction, skipped when its hash (source row + `PARSER_VERSION`) is unchanged. `scripts/load_statutes.py` loads all 12. Schema: `documents.citation`, `sections.kind` via `ADD COLUMN IF NOT EXISTS`.
- **Validated:** tests red first → 81 passed. Load: 12 inserted (3.8 s); rerun 12 unchanged (0.1 s); parser bump → 12 updated, then unchanged. SQL: 12 documents, 13,053 section rows, 0 empty text, 0 null pinpoints, 0 orphan subsections; Limitations Act s. 4 identical to source; spot checks (OLA s. 3(1) under s. 3, COTA s. 42 under Part III, HTA s. 128 under Part IX, r. 2.02 under Rule 2) correct.
- **Numbers:** 196 parts/rules, 2,946 sections, 9,911 subsections. Sections with no heading: 245, nearly all `[blank]` (57), `Repealed` or `Omitted`.
- **Next:** 1.4 — chunk, tsvector and embed (gemini-embedding-2, 1536), idempotent on text hash.

## 2026-09-25 · Phase 1 · 1.2 Acquire A2AJ statutes

- **What:** `scripts/fetch_a2aj.py` downloads `LEGISLATION-ON` and `REGULATIONS-ON` Parquet (approved: 64.1 + 63.6 MB) into `input/a2aj/`, verifies sha256 against Hugging Face's `x-linked-etag`, and appends validated lines to `input/manifest.jsonl` (`ingest/manifest.py`). `ingest/v0.py` defines the 12 v0 instruments and matches them to rows by (dataset, normalized citation) with a title guard; `scripts/match_v0.py` prints the report. Dep: pyarrow. Licence checked: Ontario permits reproducing statutes and regulations without permission; rows are marked unofficial, so the UI must say so.
- **Validated:** tests red first, then 34 new tests green (48 total). Fetch: 127.7 MB in 20 s, 2 manifest lines, `shasum -a 256` matches both; rerun → `0.0 MB downloaded, 0 new manifest lines`. Match report → `12/12 matched`, exit 0.
- **Numbers:** 12 instruments, 2,946 sections (largest: Rules of Civil Procedure 677, Insurance Act 596, City of Toronto Act 554).
- **Next:** 1.3 — load the 12 into `documents` + `sections` with pinpoints and hierarchy, idempotently.

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
