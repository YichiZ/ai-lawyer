# ai-lawyer — Ontario Injury Law Guide

Research guide to Ontario personal-injury law (plaintiff side, Toronto-focused) for paralegals and law students. Portfolio demo. Full spec: `docs/design.md` — read it before any feature work; it wins over memory.

## How we work: iterations

Every change is one small iteration, in this order. Never skip a step.

1. **Plan** — pick the next unchecked item from the current milestone in `docs/design.md`. State the exit criterion before writing code.
2. **Implement** — smallest change that meets it. Match existing code.
3. **Test** — write or update tests; run them. Unit tests for logic, one integration test per endpoint, real Vertex calls only in `scripts/check_vertex.py` and eval runs.
4. **Validate** — prove it works end to end: run the app or script and show the output. For retrieval/answer changes, run `make eval` and compare to the last baseline.
5. **Record** — append an entry to `docs/iterations.md` (what, result, numbers) and update **Lessons learned** below if anything surprised you.

**Phase plans:** before starting a phase, write `docs/phase-N-plan.md` (iterations with Accept / Tests / Validate / Stop if, like `docs/phase-1-plan.md`) and get the user's OK. Plan one phase at a time — later phases are defined against earlier baselines — and write tests inside each iteration, not ahead of it.

**Subagents:** use them for independent work that can run in parallel or would flood the main context — web/source research (e.g. finding Toronto Municipal Code chapters), codebase exploration, a code review after Implement, a second opinion on a design choice. The main session owns the loop: it states the exit criterion, checks subagent output before using it, runs Validate itself, and writes the Record. Subagents follow the same rules (no new dependency, download or stack change without the user's OK).

Stop and ask before: changing the stack, adding a dependency, any download from the web, or anything in "Rules" below.

## Commands

- `uv run -m scripts.check_vertex` — Vertex AI smoke test (6 checks). Run first in every session; if it fails, fix auth/models before anything else.
- Local auth: `gcloud auth application-default login` then `gcloud auth application-default set-quota-project <your-gcp-project-id>` (project in `.env`, see `.env.example`)
- `make up` / `make db` — start Postgres 18 + pgvector (localhost:5432) and Redis 8 (localhost:6379), dev only / apply `db/schema.sql` (idempotent).
- `make worker` — ingest worker for add-to-corpus jobs (Redis stream `ingest`; job state in `ingest_jobs`). Reviewer enqueues with `POST /ingest {url}`; `GET /ingest/{id}` shows status and stage.
- `uv run -m scripts.fetch_a2aj` — download Ontario A2AJ Parquet + manifest (idempotent). `uv run -m scripts.match_v0` — v0 match report. `uv run -m scripts.load_statutes` — load the 12 laws (idempotent). `uv run -m scripts.fetch_toronto` / `load_toronto.py` — Toronto Municipal Code ch. 719, 743, 629 (needs `pdftotext`: `brew install poppler`). `uv run -m scripts.embed_chunks` — chunk + embed changed sections (idempotent, resumable).
- `make test` — pytest against a fresh `ai_lawyer_test` database (set `TEST_DB_NAME` to use another name, e.g. one per worktree so parallel runs don't collide). `make psql` — shell into the dev DB.
- `make api` — FastAPI on :8000 (`/docs`), loads `.env` (Langfuse tracing on when keys are present). `uv run -m scripts.crawl_api` — request every section, report status + p50/p95.
- `make web` — Next.js on :3000 (reads the API at `API_URL`, default :8000). `uv run -m scripts.crawl_api --web http://localhost:3000` — crawl every rendered section page.
- `uv run -m scripts.check_gold [file]` — validate the gold set against the corpus.
- `uv run --env-file .env -m scripts.eval retrieval|answers` — Langfuse experiments on the gold set (retrieval: recall@8, MRR; answers: code metrics + Flash-Lite judge, gate trade-off).
- `make eval-suite` / `uv run --env-file .env -m scripts.eval_suite [name …]` — production eval suite (docs/evals-plan.md, results in docs/evals.md): pinpoint, search, safety, abstention, robustness, glossary; exit 1 on a missed threshold.
- `make eval` — local only: both experiments vs `evals/baseline.json` (fails on regression / failed items / hash change). `make eval-baseline` re-records it deliberately. `make ci-fixture` re-exports the CI corpus.
- `uv run --env-file .env -m scripts.profile_ask [n]` — stage latencies of the /ask pipeline (sequential). `scripts/sweep_fusion.py`, `scripts/sweep_rerank.py [candidates]`, `scripts/diagnose_retrieval.py [ids]` — offline retrieval tuning.
- `loadtest/locustfile.py` — locust load test (`Researcher` mix on a fake-model API with 4 workers; `Asker` at a low rate on the real model); commands in its docstring.
- `uv run --env-file .env -m scripts.judge_case_summaries [n]` — Flash-Lite faithfulness judge on a fixed sample of decision summaries.
- `make e2e-ci` — Playwright against a freshly rebuilt `ai_lawyer_ci` (schema + fixture), same as GitHub Actions; use it instead of reusing a stale CI-like DB.
- `make e2e` — Playwright UI tests; starts its own API (`AI_FAKE=1`, :8001) and web (:3001), so it runs beside `make api`/`make web`.
- Frontend logic that needs tests (indent levels, citations) lives in the API (`app/format.py`, pytest), so the web app has no test runner yet.
- Add commands here as they are created (`make eval`).

## Stack (decided — see design doc for why)

Python 3.13 + uv · FastAPI · Postgres 18 + pgvector + tsvector + pg_trgm · Redis 8 Streams (job dispatch; job state in Postgres `ingest_jobs`) · Docling · Vertex AI via ADC with `google-genai` · Langfuse Cloud (managed) · Next.js + Tailwind · Docker Compose.

Models: answers/summaries `gemini-3.7-flash` · rerank/context/decomposition `gemini-3.5-flash-lite` · embeddings `gemini-embedding-2` at 1536 dims · location `global`.

## Rules

- Data: A2AJ datasets first. Never bulk or programmatically download from CanLII. Show an approval table (file, URL, size) before any web/Chrome download batch. Respect `upstream_license`.
- `documents.reproduction = 'excerpt'` (Toronto Municipal Code, City copyright): never render or return full text — short excerpts with the official link only.
- Every stored document has a `sha256` and a manifest line in `input/manifest.jsonl`.
- Citations are checked in code: a quote must be an exact (whitespace-normalized) substring of its chunk, or the claim is dropped.
- No answer reaches a researcher without reviewer approval.
- No legal advice: no "you have a case", outcome predictions, claim values or computed deadlines.
- Secrets: none in code or git. Vertex AI uses ADC only (no Google keys anywhere). The only keys are Langfuse Cloud's (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`): local `.env` (gitignored) and CI secrets only.

## Lessons learned

Self-improving: when something fails, surprises you, or the user corrects you, add a dated one-line lesson here (what happened → what to do instead). Keep entries short; merge duplicates; delete lessons that stop being true. If a lesson becomes a rule, move it to Rules.

- 2026-09-25 — `gemini-3.8-flash` 504'd on most calls on Vertex `global` and 404s in `us-central1` → use `gemini-3.7-flash`; re-test 3.8 later with `check_vertex.py` before switching.
- 2026-09-25 — Default thinking made Google Search grounding loop until the deadline (87 s, 504) → always pass `thinking_level="low"` unless a task needs deep reasoning.
- 2026-09-25 — A hung Vertex call blocked a run for minutes → every client gets `HttpOptions(timeout=30_000, retry_options=...)` retrying 429/5xx.
- 2026-09-25 — On an easy question the model answered from memory without searching → grounding checks must ask for something that needs a search, and code must check `grounding_metadata.grounding_chunks` is non-empty.
- 2026-09-25 — Grounding source URIs come back as `vertexaisearch.cloud.google.com` redirects → resolve to the real URL and title before storing or citing.
- 2026-09-26 — Following a grounding redirect to the target site failed on sites that 405 a HEAD, and the fallback stored the redirect → read the redirector's `Location` header only, and drop the source when it can't be resolved.
- 2026-09-25 — ADC expired mid-session (`RefreshError: Reauthentication is needed`) → the user must run `gcloud auth application-default login` (it opens a browser); ask them, don't retry.
- 2026-09-25 — `grep` in a pipe buffered all output of a long run, so progress was invisible → print with `flush=True` and avoid piping long runs through `grep`.
- 2026-09-25 — macOS has no `timeout` command → use SDK/http timeouts, not shell `timeout`.
- 2026-09-25 — Postgres 18 images store data in `/var/lib/postgresql/18/docker` → mount the volume at `/var/lib/postgresql`, not `.../data`.
- 2026-09-25 — Hugging Face `x-linked-etag` on a HEAD (redirects off) is the file's sha256 → compare it to the manifest to skip unchanged downloads with 0 bytes.
- 2026-09-25 — A2AJ has all 12 v0 instruments; match by citation, not title (titles collide: "Limitations Act" federal vs "Real Property Limitations Act").
- 2026-09-25 — A test's `conn.transaction()` on an idle connection COMMITS, leaking rows between tests → the `conn` fixture opens an outer transaction first so inner ones are savepoints.
- 2026-09-25 — A2AJ section-map order differs from its Markdown order (Rules 2.1.01 vs 2.02) → look sections up by index, not a forward-only scan.
- 2026-09-25 — A content hash of the source alone hid a parser fix (loader said `unchanged`) → include `PARSER_VERSION` in the document hash and bump it with parser changes.
- 2026-09-25 — `gemini-embedding-2` merges a list of contents into ONE vector (and rejects multiple `Content`s) → one request per text; parallelize with a thread pool.
- 2026-09-25 — toronto.ca's copyright notice forbids copying the Municipal Code without permission → user chose local index only with excerpts + link; check a source's terms before planning to display it.
- 2026-09-25 — The preview API server ran without `--reload`, so the web app hit a stale API (500 on a new field) → launch config uses `--reload`; restart servers after API changes when in doubt.
- 2026-09-25 — pdftotext keeps PDF line wraps as newlines → rejoin lines into paragraphs (new paragraph only at labels, defined terms, `[history]`) before display or chunking.
- 2026-09-25 — Everyday wording ("sue") misses statute terms ("proceeding", "claim") in keyword search, and RRF then demotes a good vector hit (LA s. 4) → synonyms/rerank (Phase 3); judge retrieval changes on the gold set, not one query.
- 2026-09-25 — Postgres rejects `func(...)::type alias` in FROM → compute casts in a CTE.
- 2026-09-25 — Screenshots fail when the Browser pane is hidden, and clipboard writes fail in background tabs → verify with `get_page_text`/`javascript_exec`; use a background tab so the user's tab isn't disturbed.
- 2026-09-25 — Timestamps from the API are UTC → format user-facing dates in America/Toronto.
- 2026-09-25 — pdftotext's default reading order separated labels ("A. B. C.") from their paragraphs → always extract Municipal Code PDFs with `-layout`.
- 2026-09-25 — Next allows one dev server per build dir ("Another next dev server is already running") → e2e uses `NEXT_DIST_DIR=.next-e2e`.
- 2026-09-25 — Clipboard can't be verified in the built-in browser (pane hidden → `visibilityState: hidden`) → Playwright with granted clipboard permissions.
- 2026-09-25 — Code that writes to a repo file from a module-level path leaked test data into it → an autouse conftest fixture redirects such paths to `tmp_path`.
- 2026-09-26 — Langfuse `run_experiment` drops failed items silently (a run scored 59/62 after 429s) → check completeness before scoring; evals use concurrency 2, longer backoff and a 60 s timeout.
- 2026-09-26 — LLM-judge scores vary up to 8 points between identical runs; retrieval and code metrics don't → gate judge metrics at 5 points, others at 2.
- 2026-09-26 — An e2e test depended on data in the dev DB and failed in CI → e2e tests create their own data; reproduce CI with a fresh fixture-only DB (`DATABASE_URL=…/ai_lawyer_ci npm --prefix web run e2e`).
- 2026-09-26 — google-genai sends the client timeout to Vertex as a server deadline: a tight one (1.6 s) makes most calls 504 immediately → measure fallback rate before cutting timeouts.
- 2026-09-26 — gemini-3.7-flash has a long latency tail (p95 ~70 s with retries) and 429s even sequentially → keep generation off the researcher's path (background drafting); profile stages before optimizing.
- 2026-09-26 — Batch scripts on a default psycopg connection kept one transaction open for the whole run: "commit every 25" flushes were savepoints (a crash loses everything) and the held locks blocked `make db` → batch scripts use `autocommit=True`; never apply schema while a batch job runs.
- 2026-09-26 — redis-py 8 defaults `socket_timeout` to 5 s, so a 5 s `XREADGROUP` block crashed the worker with TimeoutError → set `socket_timeout` above the block time and catch `RedisError` in worker loops.
- 2026-09-26 — A guessed official URL 404'd and was retried with backoff; real pages carry menus inside `<main>` → treat 4xx as permanent (dead at once) and drop link-only blocks when parsing HTML; always try a parser on one real page before trusting fixture tests.
- 2026-09-26 — In CI a backgrounded `uv run uvicorn &` kept uv's cache lock, so setup-uv's post-step prune timed out and failed the job → start background servers from `.venv/bin/` in CI.
- 2026-09-26 — No gemini-3.7-flash quota on this project is adjustable (Vertex global = shared capacity; only a 50M input-tokens/min cap at 0% use), and the account is on the free trial → 429s and the draft tail are shared-capacity limits; the fixes are Provisioned Throughput (needs a paid account) or fewer/shorter calls, not a quota request.
- 2026-09-26 — The first abstention scorer counted decision-grounded answers as "unsourced", and the glossary judge called non-answers "faithful" → read every failing item (and a sample of passing ones) before trusting a new eval's number.
- 2026-09-26 — A background Python script writing to a file printed nothing until it exited, and `cat > f 2>/dev/null || …` truncated a script to 0 bytes → use `python -u` / `flush=True`, and write files with the Write tool.
- 2026-09-26 — `pkill -f next-server` killed the user's dev server too, and a leaked `next start` served a stale build → kill test servers by their exact port pattern (`next start --port 3002`), never generic names.
- 2026-09-25 — CanLII terms ban bulk download and it is suing an AI company over it; A2AJ has no Ontario Superior Court decisions → link out via CanLII API metadata; say the gap in the UI.
