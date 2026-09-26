# Phase 1 plan — iterations and acceptance criteria

Phase exit (from `docs/design.md`): every section browsable; one reviewed answer with a verified quote.

Each iteration lists **Accept** (all must hold), **Tests** (automated, written first where there is logic), **Validate** (the command to run and the output that proves it), and **Stop if** (conditions that block the iteration and need a decision). An iteration is done only when every Accept line is shown true in output recorded in `docs/iterations.md`.

Common to every iteration:
- `uv run scripts/check_vertex.py` → 6/6 at session start.
- `make test` green, with no skipped tests except those marked `vertex` (real-call tests, run on demand).
- No secrets in the diff (`git diff | grep -iE 'api[_-]?key|secret|password'` empty, except the seeded Postgres dev password in compose).
- New dependencies approved before `uv add`.
- Subagents may do independent parts in parallel (see CLAUDE.md): source research in 1.2 and 1.5, a code review after each Implement, UI and API work in 1.9/1.10. Their output is checked by the main session; validation is always run by the main session.

---

## 1.1 Database and schema

**Accept**
- `docker compose up -d db` starts `pgvector/pgvector:pg18`; healthcheck reports `healthy` within 30 s.
- `make db` applies `db/schema.sql` idempotently: running it twice exits 0 with no errors.
- Tables exist: `documents`, `sections`, `chunks`, `users`, `answers`, with columns from the design doc's data model.
- Constraints: `documents.sha256` unique and not null; `sections.document_id` and `chunks.document_id` FKs with `ON DELETE CASCADE`; `answers.status` limited to `pending_review | approved | edited | rejected`; `users.role` limited to `researcher | reviewer`.
- Indexes: HNSW (`halfvec_cosine_ops`) on `chunks.embedding`, GIN on `chunks.tsv`, GIN trigram on `documents.title` and `sections.heading`, btree on `(document_id, sort_order)`.
- `chunks.tsv` is a generated column (`english` config), so it can't drift from `text`.
- Extensions `vector` (≥ 0.8) and `pg_trgm` installed.

**Tests**
- Insert document → section → chunk with a 1536-dim vector; read it back.
- Duplicate `sha256` raises a unique violation.
- Bad `answers.status` / `users.role` raises a check violation.
- Deleting a document cascades to its sections and chunks.
- Wrong vector dimension (e.g. 768) is rejected.
- Index test queries `pg_indexes` and asserts each index by name and method.

**Validate**
- `docker compose ps` → db `healthy`; `make db` twice → no errors; `psql -c '\d chunks'` shows `embedding halfvec(1536)` and the generated `tsv`.

**Stop if** Postgres 18 + pgvector image is unavailable on this machine's architecture.

---

## 1.2 Acquire A2AJ statutes

**Accept**
- Approval table shown before any download: file, URL, size. Download starts only after "OK".
- Only Ontario files needed for the v0 list are downloaded (no full-country pull unless the dataset isn't split by jurisdiction — then ask).
- Each downloaded file has exactly one line in `input/manifest.jsonl` with `url`, `source=a2aj-laws`, `title`, `jurisdiction=ON`, `doc_type`, `upstream_license`, `sha256`, `fetched_at`; the `sha256` matches `shasum -a 256` of the file.
- Re-running the fetch script skips files whose `sha256` is already in the manifest: 0 bytes downloaded, 0 manifest lines added.
- A match report lists every v0 instrument (11 named in the design doc; Acts and regulations) as `matched` with its section count, or `missing` with the closest candidates. No silent drops.
- Manifest lines are validated on write: a line missing a required field fails the script.

**Tests**
- Manifest writer: required fields enforced; duplicate `sha256` not appended.
- Title matcher: exact, punctuation-insensitive ("Occupiers' Liability Act" vs "Occupiers Liability Act"), and year variants ("Limitations Act, 2002"); does not match "Limitations Act" (federal) or repealed versions.

**Validate**
- Fetch script run twice: first prints bytes downloaded, second prints `0 new`.
- Match report printed; count of `matched` ≥ 10 of 11, any `missing` explained.

**Stop if** the dataset's licence forbids redistribution in a portfolio demo, or a v0 instrument isn't in A2AJ (ask: source it from ontario.ca/e-Laws via an approved download instead?).

---

## 1.3 Load statutes into Postgres

**Accept**
- Every matched v0 instrument is one `documents` row with `slug` (e.g. `limitations-act-2002`), `short_name`, `url`, `source`, `upstream_license`, `sha256`, `in_force_from`.
- Sections keep hierarchy (Act > Part > section > subsection) via `parent_id` and a stable `sort_order` that matches the official order.
- Pinpoints are normalized: `s-4`, `s-4-1` (for s. 4(1)), `s-7-1-a`; displayed form `s. 4(1)(a)` derivable; unique per document.
- Section text preserved exactly as the source (no trimming inside text), so quotes verify against it later.
- Load is one transaction per document: a failure mid-document leaves no partial rows.
- Re-running the loader: 0 inserted, 0 updated for unchanged `sha256`.
- Changed source (simulated with a fixture) replaces that document's sections, not duplicates them.

**Tests**
- Pinpoint parser: `4`, `4(1)`, `4(1)(a)`, `4.1`, `2(1)(a)(i)`, `Schedule B` → expected slugs and display forms.
- Tree builder on a small fixture: parents before children, correct `sort_order`.
- Idempotency: load fixture twice → same row counts.
- Rollback: fixture with a malformed section → no rows for that document.

**Validate**
- Loader output: per-document section counts; second run `0 new`.
- SQL spot checks: Limitations Act s. 4 text equals the source's s. 4; count of documents = matched count from 1.2; zero sections with empty text or null pinpoint.

---

## 1.4 Chunk, index, embed

**Accept**
- One chunk per section; sections over ~800 tokens split at subsection boundaries, never mid-sentence. Every chunk carries `pinpoint` and `section_ids`.
- Every section's text is covered by at least one chunk (no orphan sections).
- Embeddings: `gemini-embedding-2`, 1536 dims, `embedding_model` recorded; batched (≤ 100 texts per call), with the standard 30 s timeout and 429/5xx retries.
- Idempotent: rerun makes 0 embedding calls when chunk text is unchanged (keyed on text hash).
- Partial failure is resumable: kill mid-run, rerun, only missing embeddings are computed.
- Keyword search works: `tsv @@ websearch_to_tsquery('limitation period')` returns Limitations Act chunks.
- Vector search works: nearest neighbour for an embedding of "time limit to sue" includes Limitations Act s. 4 in the top 5.

**Tests**
- Chunker: short section → 1 chunk; long section → split on subsections, each ≤ limit, concatenation equals original text.
- Embed step with a fake client: batches sized correctly; unchanged hashes skipped; failure on batch 2 leaves batch 1 stored.

**Validate**
- Run prints: chunks created, embedding calls, tokens, elapsed; second run prints `0 embedding calls`.
- SQL: `count(*) where embedding is null` = 0; the two search spot checks above printed with results.
- Cost for the run recorded in `docs/iterations.md`.

---

## 1.5 Toronto Municipal Code layer

**Accept**
- Web search finds the Municipal Code chapters for sidewalks, snow clearing and roads (expected: Ch. 743 Streets and Sidewalks, Ch. 719 Snow/Ice as they exist); approval table (file, URL, size) shown before download.
- robots.txt checked and respected; ≤ 1 request/s; no login-gated pages.
- Each file in `input/` with a manifest line (`source=toronto-municipal-code`, licence noted).
- Parsed into document + sections + chunks with pinpoints like `743-9` (§ 743-9), same idempotency as 1.3/1.4.
- Parser choice justified: if the PDFs have a text layer, a lighter approach is proposed before adding Docling.
- Spot check: one section's parsed text matches the PDF text for that section (whitespace-normalized).

**Tests**
- Parser on a small saved fixture page: section numbers and headings extracted in order.

**Validate**
- Load run twice (second `0 new`); SQL shows the chapters with section counts; the spot-check comparison printed.

**Stop if** toronto.ca terms or robots forbid automated fetch — fall back to manual download by the user.

---

## 1.6 Law library API

**Accept**
- `GET /laws` → documents grouped by kind with slug, title, citation, section count, `in_force_from`.
- `GET /laws/{slug}` → document metadata + section tree (headings and pinpoints, no full text).
- `GET /laws/{slug}/{pinpoint}` → full text, heading, parent chain (breadcrumb), prev/next pinpoints, source URL, "as of" date, `upstream_license`.
- Unknown slug or pinpoint → 404 with a JSON error, never 500. Invalid pinpoint characters → 422.
- Responses use the consistent envelope from the rules (`data`, `error`, `meta`).
- DB access through parameterized queries only.
- p95 for `GET /laws/{slug}/{pinpoint}` < 100 ms locally over all sections.

**Tests**
- One integration test per endpoint against a seeded test DB, plus 404 and 422 cases.

**Validate**
- `make dev` starts API; crawl script requests every section in the DB → prints `N/N 200`, zero non-200, p50/p95 latency.

---

## 1.7 Law library frontend

**Accept**
- Library page: Act → Part → section tree for every document, with in-force date.
- Section page `/laws/{slug}/{pinpoint}`: official text in the serif face with hanging indents for (1)/(a)/(i); breadcrumb; prev/next; source line "Official text as of <date> · Source: … via A2AJ"; copy-citation button (McGill style, e.g. *Limitations Act, 2002*, SO 2002, c 24, Sched B, s 4).
- Tokens from the design doc's palette in light and dark; no AI summary shown yet (Phase 4), so no unlabeled AI text.
- Keyboard: every link and button reachable by Tab; visible focus.
- 404 page for unknown sections.

**Tests**
- Citation formatter unit tests (Act, Act with schedule, regulation, subsection pinpoint).

**Validate**
- `make dev` runs API + web; crawl of every section URL → `N/N 200`; screenshots of library and one section page in light and dark; axe/Lighthouse a11y score reported (target 100, anything less listed).

---

## 1.8 `POST /ask` drafts an answer

**Accept**
- Request validated: question 5–1000 chars, else 422.
- Retrieval: top 50 keyword + top 50 vector in parallel, fused with RRF (k = 60), top 8 kept; each source returned with pinpoint, snippet, and fused score.
- Sources are returned in the response immediately; the answer is stored with `status=pending_review` and its id returned.
- Grounding gate: if the best score is below the threshold, no model call — "not found in the laws we cover" with the 3 closest passages. Threshold is a named constant with the value used recorded.
- Model returns structured `claims: [{text, chunk_id, quote}]` (3.7 Flash, low thinking, timeout + retries).
- Code verifies every quote is a whitespace-normalized exact substring of the named chunk, and that `chunk_id` is one of the 8 retrieved; failing claims dropped, one retry, two failures → refusal path. Dropped claims stored for the reviewer.
- Guardrail prompt: no "you have a case", outcomes, values or computed deadlines. Out-of-scope questions (e.g. criminal, BC law) are refused.
- Latency (sources) and total latency logged per request.

**Tests**
- Quote verifier: exact, whitespace variants, curly vs straight quotes (decide and document), partial, wrong chunk, chunk not in the retrieved set.
- RRF: known ranks → known fused order; ties stable.
- Gate: below-threshold path makes zero model calls (fake client asserts not called).
- Endpoint integration test with a fake model client: pending answer persisted, claims stored, sources returned.

**Validate** (real Vertex)
- Three questions: "How long do I have to sue after an injury in Ontario?" (expect Limitations Act s. 4, ≥ 1 verified quote); "I slipped on an icy sidewalk in Toronto — who do I notify?" (expect City of Toronto Act / Municipal Code); "How do I appeal a speeding ticket in BC?" (expect refusal). Print sources, claims, verified/dropped counts, latencies.

---

## 1.9 Review workflow API

**Accept**
- Two seeded users (researcher, reviewer); role taken from a demo header/cookie, no real auth (documented as demo-only).
- `GET /review/queue` (reviewer only, else 403): pending answers, risk-flagged first (dropped claims, refusal retry, low scores), oldest first within a tier.
- `POST /answers/{id}/review`: `approve`; `edit` requires `final_markdown` + non-empty note; `reject` requires a reason from the fixed list. Missing fields → 422.
- Only `pending_review` answers can be reviewed; reviewing twice → 409.
- `GET /answers/{id}` for a researcher: pending → question, sources, "Awaiting review", no draft text; approved/edited → final text + "Reviewed by <name> on <date>" (+ "edited by reviewer"); rejected → reason, no draft text.
- Every state change stamps `reviewed_by`, `reviewed_at`; drafts are never overwritten (edits go to `final_markdown`).

**Tests**
- Integration: each decision path, 403 for researcher on queue/review, 409 double review, 422 missing note/reason, researcher never sees draft before approval.

**Validate**
- curl walkthrough against the running API: ask → queue shows it → approve → researcher GET shows the reviewed answer with its verified quote.

---

## 1.10 Ask and Review pages

**Accept**
- Ask page: sources appear on submit; answer area shows "Awaiting review" until approved; citation chips open the passage in a side panel with the quote highlighted.
- Review page (reviewer role only): question, each claim beside its verified quote and source link, dropped claims, scores, risk flags; approve / edit (note required) / reject (reason required) with inline validation.
- Role switch in the header (demo only, clearly labelled).
- Released answers show "Reviewed by <name> on <date>" and the no-advice notice.
- Errors (API down, timeout) show a user-friendly message, not a blank page.

**Tests**
- One Playwright flow: ask → switch to reviewer → approve → switch back → reviewed answer with quote visible; citation chip opens the passage.

**Validate** (phase exit)
- Run the flow in the browser with a real question; screenshots of pending, review queue, and released answer; SQL shows the answer `approved` with ≥ 1 verified claim. Crawl from 1.7 still `N/N 200`. Record both halves of the phase exit criterion in `docs/iterations.md`.
