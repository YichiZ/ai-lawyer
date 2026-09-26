# Ontario Injury Law Guide

A research guide to Ontario personal-injury law (plaintiff side, Toronto-focused) for paralegals and law students.
Browse the laws, search them in everyday or legal words, and ask research questions whose answers a human reviewer
approves before release. Every statement in an answer carries a quote that is checked in code against the official text.

> **Portfolio demo. Not legal advice.** The app gives no outcome predictions, no claim values and no computed deadlines,
> and no answer reaches a researcher without a reviewer's approval.

## What it does

- **Law library:** 12 Ontario statutes and regulations, Toronto Municipal Code ch. 629, 719 and 743 (excerpts only,
  City copyright), and 1,660 Court of Appeal and Supreme Court of Canada injury decisions from the open
  [A2AJ](https://huggingface.co/a2aj) datasets. Each section has a plain-language summary, glossary terms and a list of
  the decisions that cite it.
- **Search:** one box with typeahead, citation jumps (`LA s. 4`, `2016 ONCA 585 at para 12`) and hybrid keyword and
  vector search.
- **Ask:** sources come back in under a second. A draft is then written in the background: retrieval → Flash-Lite
  rerank → gemini-3.7-flash → quote verification → review queue. If the library has no close match, the grounding gate
  says "not found".
- **Review:** the reviewer approves, edits or rejects each answer. Risky drafts (dropped claims, not found, web
  answers) come first.
- **Web fallback:** an opt-in Google Search answer, labelled "from the web" and reviewed like any other. The reviewer
  can add official pages (ontario.ca, canada.ca, ontariocourts.ca, scc-csc.ca, toronto.ca) to the library. A Redis
  Streams worker fetches each page (obeying robots.txt, ≤ 1 request/s), then parses, chunks and embeds it.
- **Topic guides:** 5 practice areas. Each section is drafted by the answer pipeline and shown only after review.

## Stack

Python 3.13 + uv · FastAPI · Postgres 18 + pgvector + tsvector + pg_trgm · Redis 8 Streams (job dispatch; job state in
Postgres) · Vertex AI via Application Default Credentials (`gemini-3.7-flash`, `gemini-3.5-flash-lite`,
`gemini-embedding-2` at 1536 dims) · Langfuse Cloud (tracing and evals) · Next.js 16 + Tailwind 4 · Playwright, axe and
Lighthouse CI · Docker Compose.

The design, its trade-offs and the milestones are in [docs/design.md](docs/design.md). Every iteration, with its
numbers, is logged in [docs/iterations.md](docs/iterations.md).

## Quick start

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 24, `pdftotext` (`brew install poppler`) and the
`gcloud` CLI with access to a Google Cloud project that has Vertex AI enabled.

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project <your-project>
uv sync && npm ci --prefix web
make db                              # Postgres + Redis in Docker, schema applied
uv run scripts/check_vertex.py       # Vertex smoke test (6 checks)
```

Optional: put Langfuse Cloud keys in a gitignored `.env` (`chmod 600`) to turn on tracing and evals:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
```

There are no Google API keys: Vertex AI uses ADC only.

### Build the corpus

Each script is idempotent: it only redoes work whose source hash changed. The fetch scripts download from A2AJ
(Hugging Face) and toronto.ca, and record a sha256 and a manifest line for every file in `input/manifest.jsonl`.

```bash
uv run scripts/fetch_a2aj.py && uv run scripts/load_statutes.py        # statutes and regulations
uv run scripts/fetch_toronto.py && uv run scripts/load_toronto.py      # Toronto Municipal Code
uv run scripts/fetch_a2aj.py --caselaw && uv run scripts/load_caselaw.py
uv run scripts/contextualize_chunks.py && uv run scripts/embed_chunks.py
uv run scripts/summarize_sections.py && uv run scripts/summarize_cases.py
uv run scripts/build_glossary.py && uv run scripts/build_citations.py
uv run --env-file .env scripts/build_guides.py                          # drafts go to the review queue
```

The LLM steps (context, summaries, guides) cost a few dollars on Vertex AI; the context and summary scripts print an estimate first.

### Run

```bash
make api      # FastAPI on http://localhost:8000 (/docs)
make worker   # ingest worker for "Add to library" jobs
make web      # Next.js on http://localhost:3000
```

Switch between the **researcher** and **reviewer** demo roles in the page header.

## Tests and quality gates

```bash
make test          # pytest against a fresh ai_lawyer_test DB (needs Redis for the job-queue tests)
make e2e-ci        # Playwright + axe against a fresh fixture-only DB, fake model (as in CI)
make lighthouse    # production build + Lighthouse budgets
make eval          # gold-set experiments in Langfuse vs evals/baseline.json (local only; uses Vertex)
```

- **Evals** (62 gold questions, 15 out of scope):
  - retrieval: recall@8 1.00, MRR 0.91
  - answers: verified-claim rate 1.00, facts covered 0.98, citation supported 0.95, no advice 1.00
  - summaries: faithful 0.98

  The gate fails on a drop of more than 2 points (5 points for LLM-judge metrics) or on a change to the corpus or gold
  hash.
- **CI** (GitHub Actions): unit/integration tests, Playwright end-to-end tests with axe on 10 pages × 2 themes, and
  Lighthouse (accessibility 100, CLS 0).
- **Load test:** see [loadtest/locustfile.py](loadtest/locustfile.py) and the results in
  [docs/iterations.md](docs/iterations.md).

## Layout

```
app/        FastAPI API: retrieval, answering, review, job queue, web fallback
ingest/     parsers and loaders (A2AJ statutes and cases, Toronto PDFs, web pages), chunking, Vertex clients
evals/      gold set, metrics, baseline gate, CI fixture
scripts/    fetch / load / embed / summarize / eval / worker entry points
web/        Next.js app and Playwright specs
db/         schema.sql (idempotent)
loadtest/   locust scenarios
docs/       design doc, phase plans, iteration log
```

## Data and licences

- A2AJ datasets: each document keeps its `upstream_license`, shown on its page.
- Toronto Municipal Code: © City of Toronto. The app indexes it locally and shows short excerpts with a link to the
  official PDF.
- Web pages: only the five official domains above can be added. Each page is stored with its source and a licence note.
- CanLII: nothing is ever downloaded in bulk or programmatically. Ontario Superior Court decisions are not in A2AJ, and
  the case pages say so.

## Known limits

- **Answer drafts are slow:** p95 is 11.4 s against an 8 s target. The time is Gemini generation on Vertex AI.
- **Pages are heavier than the design target:** LCP is about 2.5 s and JavaScript about 140 KB, against 1.5 s and 100 KB.
- **Decision summaries are hard to read:** they average grade 13.4, against a target of 8–10.
