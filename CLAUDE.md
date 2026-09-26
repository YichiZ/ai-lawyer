# ai-lawyer — Ontario Injury Law Guide

Research guide to Ontario personal-injury law (plaintiff side, Toronto-focused) for paralegals and law students. Portfolio demo. Full spec: `docs/design.md` — read it before any feature work; it wins over memory.

## How we work: iterations

Every change is one small iteration, in this order. Never skip a step.

1. **Plan** — pick the next unchecked item from the current milestone in `docs/design.md`. State the exit criterion before writing code.
2. **Implement** — smallest change that meets it. Match existing code.
3. **Test** — write or update tests; run them. Unit tests for logic, one integration test per endpoint, real Vertex calls only in `scripts/check_vertex.py` and eval runs.
4. **Validate** — prove it works end to end: run the app or script and show the output. For retrieval/answer changes, run `make eval` and compare to the last baseline.
5. **Record** — append an entry to `docs/iterations.md` (what, result, numbers) and update **Lessons learned** below if anything surprised you.

**Subagents:** use them for independent work that can run in parallel or would flood the main context — web/source research (e.g. finding Toronto Municipal Code chapters), codebase exploration, a code review after Implement, a second opinion on a design choice. The main session owns the loop: it states the exit criterion, checks subagent output before using it, runs Validate itself, and writes the Record. Subagents follow the same rules (no new dependency, download or stack change without the user's OK).

Stop and ask before: changing the stack, adding a dependency, any download from the web, or anything in "Rules" below.

## Commands

- `uv run scripts/check_vertex.py` — Vertex AI smoke test (6 checks). Run first in every session; if it fails, fix auth/models before anything else.
- Local auth: `gcloud auth application-default login` then `gcloud auth application-default set-quota-project long-indexer-507414-n0`
- `make up` / `make db` — start Postgres 18 + pgvector (localhost:5432, dev only) / apply `db/schema.sql` (idempotent).
- `make test` — pytest against a fresh `ai_lawyer_test` database. `make psql` — shell into the dev DB.
- Add commands here as they are created (`make dev`, `make eval`).

## Stack (decided — see design doc for why)

Python 3.13 + uv · FastAPI · Postgres 18 + pgvector + tsvector + pg_trgm · Redis 8 Streams (job dispatch; job state in Postgres `ingest_jobs`) · Docling · Vertex AI via ADC with `google-genai` · Langfuse (self-hosted) · Next.js + Tailwind · Docker Compose.

Models: answers/summaries `gemini-3.7-flash` · rerank/context/decomposition `gemini-3.5-flash-lite` · embeddings `gemini-embedding-2` at 1536 dims · location `global`.

## Rules

- Data: A2AJ datasets first. Never bulk or programmatically download from CanLII. Show an approval table (file, URL, size) before any web/Chrome download batch. Respect `upstream_license`.
- Every stored document has a `sha256` and a manifest line in `input/manifest.jsonl`.
- Citations are checked in code: a quote must be an exact (whitespace-normalized) substring of its chunk, or the claim is dropped.
- No answer reaches a researcher without reviewer approval.
- No legal advice: no "you have a case", outcome predictions, claim values or computed deadlines.
- Secrets: none in code or `.env` — ADC only.

## Lessons learned

Self-improving: when something fails, surprises you, or the user corrects you, add a dated one-line lesson here (what happened → what to do instead). Keep entries short; merge duplicates; delete lessons that stop being true. If a lesson becomes a rule, move it to Rules.

- 2026-09-25 — `gemini-3.8-flash` 504'd on most calls on Vertex `global` and 404s in `us-central1` → use `gemini-3.7-flash`; re-test 3.8 later with `check_vertex.py` before switching.
- 2026-09-25 — Default thinking made Google Search grounding loop until the deadline (87 s, 504) → always pass `thinking_level="low"` unless a task needs deep reasoning.
- 2026-09-25 — A hung Vertex call blocked a run for minutes → every client gets `HttpOptions(timeout=30_000, retry_options=...)` retrying 429/5xx.
- 2026-09-25 — On an easy question the model answered from memory without searching → grounding checks must ask for something that needs a search, and code must check `grounding_metadata.grounding_chunks` is non-empty.
- 2026-09-25 — Grounding source URIs come back as `vertexaisearch.cloud.google.com` redirects → resolve to the real URL and title before storing or citing.
- 2026-09-25 — ADC expired mid-session (`RefreshError: Reauthentication is needed`) → the user must run `gcloud auth application-default login` (it opens a browser); ask them, don't retry.
- 2026-09-25 — `grep` in a pipe buffered all output of a long run, so progress was invisible → print with `flush=True` and avoid piping long runs through `grep`.
- 2026-09-25 — macOS has no `timeout` command → use SDK/http timeouts, not shell `timeout`.
- 2026-09-25 — Postgres 18 images store data in `/var/lib/postgresql/18/docker` → mount the volume at `/var/lib/postgresql`, not `.../data`.
- 2026-09-25 — CanLII terms ban bulk download and it is suing an AI company over it; A2AJ has no Ontario Superior Court decisions → link out via CanLII API metadata; say the gap in the UI.
