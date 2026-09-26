# Iteration log

One entry per iteration, newest first. Format: date · milestone · what changed · how it was validated · numbers · next.

## 2026-09-26 · Phase 3 · 3.5 Chunk context — kept (+ rerank safety net)

- **What:** `ingest/contextualize.py` + `scripts/contextualize_chunks.py`: gemini-3.5-flash-lite writes 1–2 situating sentences per chunk from the law title, the outline of the chunk's Part (≤ 60 headings) and the chunk text; stored in `chunks.situating`, used in the embedding input only (keyword `tsv` unchanged); writing it clears the embedding so only those chunks re-embed; `sync_chunks` carries situating sentences over for unchanged chunks; `--clear` reverts. Rerank safety net: the reranker may reorder but not drop the fused top 3 (`KEEP_FUSED`) — one sweep showed it dropping a fused #1 (city-08).
- **Run:** estimate $1.73 (3.5M input tokens at $0.30/M, output $2.50/M); 3,447 situating calls in 452 s, 3,447 re-embeds in 103 s, 0 missing. Samples read well (e.g. LA s. 4: "establishes the standard two-year basic limitation period… unless a specific exception dictates otherwise").
- **Offline:** fused-only MRR **0.847 → 0.895** (this is what `/search` and the rerank fallback use); fused + rerank 0.901 / 0.924 / 0.923 across three runs (reranker noise), recall 1.000 with the safety net.
- **Validated:** tests red first → 289 passed; `make eval` → no regression; MRR 0.908 → 0.913, has verified claim 0.984 → 1.000, facts 0.952 → 0.968, faithful 0.902 → 0.919, in-scope answered 0.984 → 1.000. Baseline re-recorded ([answers run](https://us.cloud.langfuse.com/project/cmuhr5jjm053rad0chpar3j5x/datasets/cmuhu62p505bsad0cefumvo3x/runs/fb056871-61f8-4600-9c5d-c28b7d8c9251)).
- **Concern for 3.6:** sources p95 4.99 s under eval load (rerank calls occasionally slow; one sweep showed rerank p95 4.8 s).
- **Next:** 3.6 latency.

## 2026-09-26 · Phase 3 · 3.4 Listwise rerank — kept

- **What:** `app/rerank.py`: gemini-3.5-flash-lite orders the fused top candidates (ids + citation + first 120 words) in one JSON call; unknown/duplicate ids ignored, missing ids keep fused order, errors or malformed output fall back to fused order (flagged); traced as a `rerank` span. Wired into `/ask` and both eval experiments (not `/search`, kept fast). `scripts/sweep_rerank.py [candidates]`. Also: `tracing.update_current_generation` no longer logs "No active span" outside a trace (checks the OpenTelemetry span context).
- **Sweep (offline):** fused 3.3 MRR 0.847 → rerank of top 30: **0.904**, rerank p95 1.52 s; top 20: **0.917**, p95 1.27 s → `RERANK_CANDIDATES = 20` (design said 30; 20 was better and faster). 0 fallbacks.
- **Validated:** tests red first → 254 passed; `make eval` → no regression, **MRR 0.847 → 0.908**; sources latency with rerank p50 1.42 s / **p95 1.87 s** (target < 2 s) under eval concurrency. Baseline re-recorded ([answers run](https://us.cloud.langfuse.com/project/cmuhr5jjm053rad0chpar3j5x/datasets/cmuhu62p505bsad0cefumvo3x/runs/21ebe570-2751-4268-937f-cdbbf356b00c)): has verified claim 0.984, facts 0.952, citation supported 0.967, faithful 0.902.
- **Next:** 3.5 chunk context.

## 2026-09-26 · Phase 3 · 3.2 Synonym expansion — reverted

- **What:** 55 curated everyday → legal phrases (`app/synonyms.tsv`, word-boundary matching, no chaining; 5 tests), applied to the keyword query only.
- **Result (offline sweep):** with 3.3 fusion: recall@8 1.000 → 1.000, MRR 0.847 → **0.844**; with Phase 2 fusion: 0.887 → 0.887, MRR 0.624 → 0.611. No gain: once fusion stopped burying vector hits, the vocabulary gap no longer costs anything on this gold set.
- **Decision:** not kept (plan rule); module, list and tests deleted — recoverable from commit d293141. Revisit only if a keyword-heavy query set (exact terms, citations) shows a gap.
- **Next:** 3.4 rerank.

## 2026-09-26 · Phase 3 · 3.3 Fusion tuning — kept

- **What:** weighted RRF (`rrf(..., weights)`), keyword mode `and_or` (tried, not kept), `scripts/sweep_fusion.py` (offline: each gold question embedded once, every variant scored with the same metric). Chosen: **k 10, keyword weight 0.3** (`RRF_K`, `KEYWORD_WEIGHT`).
- **Sweep (offline, recall@8 / MRR):** Phase 2 (k 60, 1:1) 0.887 / 0.624 · and_or 0.887 / 0.643 · depth 100 0.806 / 0.607 · weights 0.5:1 0.919 / 0.700 · 0.3:1 0.952 / 0.762 · k 10 0.968 / 0.677 · k 10 + 0.5:1 1.000 / 0.805 · **k 10 + 0.3:1 1.000 / 0.847** · k 5 + 0.5:1 1.000 / 0.857 · k 20 + 0.5:1 1.000 / 0.760 · vector only 1.000 / 0.919. Kept hybrid (not vector-only) because the gold set has few exact-term / citation queries; picked a middle point rather than the grid extreme.
- **Validated:** tests red first (weighted RRF) → pass; `make eval` → no regression, improved: **recall@8 0.887 → 1.000, MRR 0.626 → 0.847, has verified claim 0.919 → 1.000, facts covered 0.847 → 0.968, in-scope answered 0.919 → 1.000**; citation supported 0.956, faithful 0.903 (within judge tolerance). All 5 previously unverified in-scope items now answer with verified quotes. Baseline re-recorded ([run](https://us.cloud.langfuse.com/project/cmuhr5jjm053rad0chpar3j5x/datasets/cmuhu62p505bsad0cefumvo3x/runs/c3fd0620-74f1-47e0-9830-04e05e68bae3)).
- **Next:** 3.2 synonyms delta; 3.4 rerank.

## 2026-09-26 · Phase 3 · 3.7 Search and typeahead

- **What:** `app/search.py` + `GET /suggest?q=` (citations jump to a section: "s. 4(1)", "OLA s 6.1", "r. 2.02", "§ 743-9", law named by abbreviation or title; otherwise pg_trgm word similarity on law titles and section headings) and `GET /search?q=` (hybrid retrieval top 20 grouped by law; `meta.ask_this` for question-shaped queries). Web: header search box (combobox + listbox ARIA, `/` to focus, arrows/Enter, debounced server action), `/search` results page with "Ask this" → `/ask?q=` prefilled.
- **Validated:** tests red first → 29 new (246 total); Playwright +2 flows (citation → section; heading typeahead; question → results → Ask this prefilled) → 7/7 on a fresh fixture-only DB. `/suggest` over 60 requests: **p50 7.5 ms, p95 9.0 ms** (target < 100 ms); samples: "OLA s 6.1" → s. 6.1 Notice period — injury from snow or ice; "§ 719-2" → § 719-2 Time limit for removal of snow.
- **Bug found by the e2e test:** Escape on a `type=search` input clears it natively, so closing suggestions wiped the query → Escape now only closes the list when it is open.
- **Next:** finish 3.3 (fusion) once `make eval` returns; then 3.2 synonyms, 3.4 rerank, 3.5 context, 3.6 latency.

## 2026-09-26 · Phase 3 · 3.1 Miss analysis (+ metric fix)

- **What:** `retrieve` split into `keyword_ranking` / `vector_ranking` (results identical: 0.855 / 0.601). `scripts/diagnose_retrieval.py` prints each miss's rank in the keyword, vector and fused lists (depth 200) with the query terms.
- **Findings (9 misses):**

  | id | keyword | vector | fused | cause |
  |---|---|---|---|---|
  | lim-02 | 54 | **1** | 14 | fusion buries a vector #1 |
  | lim-03 | 101 | **1** | 10 | fusion |
  | lim-07 | — | **1** | 12 | fusion |
  | lim-09 | — | **1** | 9 | fusion |
  | proc-02 | 158 | **1** | 15 | fusion |
  | proc-07 | 67 | 4 | 15 | fusion |
  | mv-11 | — | 5 | 16 | fusion + vocabulary |
  | mv-01 | — | 5 | 17 | vocabulary (and metric, below) |
  | dog-09 | — | — | — | **metric bug** |

  The OR'ed keyword query ("limit", "act", "claim", …) matches broadly; chunks in both lists at middling ranks outscore a vector-only #1 under RRF.
- **Metric bug fixed:** split chunks are labelled by their first subsection but contain several; recall now credits every subsection a chunk covers (`chunk_covers`, from `section_ids`, parent id excluded). dog-09 is a fused #1; mv-01 was also a hidden hit. Same system, corrected measurement: **recall@8 0.855 → 0.887, MRR 0.602 → 0.626**; baseline re-recorded (answers unchanged).
- **Plan change:** fusion (3.3) before synonyms (3.2) — it targets 7 of the remaining 7 misses.
- **Next:** 3.3 fusion tuning.

## 2026-09-26 · Phase 2 · 2.5 Baseline + CI — Phase 2 complete

- **What:** `evals/baseline.py` (corpus hash = sorted document sha256s, gold hash = file sha256; `compare` fails on a drop > 2 points, > 5 for the two judge metrics, a missing metric or a hash change). `scripts/eval.py gate | record [--from-latest]`; `make eval`, `make eval-baseline`. Eval runs: concurrency 2, 8 retries up to 60 s backoff, 60 s timeout, and any failed item fails the run. `GATE_MAX_DISTANCE` 0.35 → **0.30** (user-approved). CI fixture corpus (`tests/fixtures/corpus`, 3 documents / 275 sections / 52 chunks with embeddings, `make ci-fixture`) + GitHub Actions: `test` (pytest, Postgres 18 + pgvector service) and `e2e` (fixture corpus, Playwright, fake model). Evals stay local (user decision; no Workload Identity Federation).
- **Found on the way:** (1) a run with 3 items lost to 429/504 had silently scored 59/62 → completeness check; (2) three runs showed judge metrics swinging (faithful 0.852–0.930, citation 0.938–0.966) while retrieval and code metrics were stable → judge tolerance 5 points (departure from the design's flat 2, flagged to the user); (3) first CI run failed: an e2e test relied on a pending answer existing in the dev DB → the test now creates its own; reproduced against a fresh fixture-only DB first.
- **Validated:** tests red first → 214 passed. CI run 2 green (test + e2e). Baseline recorded from complete runs ([retrieval](https://us.cloud.langfuse.com/project/cmuhr5jjm053rad0chpar3j5x/datasets/cmuhu62p505bsad0cefumvo3x/runs/1921649d-ee0b-4c4f-be98-f52d9311e9ac), [answers](https://us.cloud.langfuse.com/project/cmuhr5jjm053rad0chpar3j5x/datasets/cmuhu62p505bsad0cefumvo3x/runs/397246f8-3f5e-40a5-b533-0994280b96ad)). Deliberately broken retrieval (top 2, not committed) → gate FAILS: recall@8 −25.8, MRR −6.1. Fresh `make eval` on unchanged code → "no regression vs baseline" (largest move faithful −1.8).
- **Baseline (`evals/baseline.json`):** recall@8 0.855 · MRR 0.602 · has verified claim 0.919 · verified claim rate 0.994 · facts covered 0.855 · citation supported 0.966 · faithful 0.930 · no advice 1.000 · in-scope not refused 0.919 · out-of-scope refused 0.933. App latency (earlier unthrottled run): sources p95 553 ms, total p95 9.2 s (over the 8 s target).
- **Phase 2 exit:** gold set ✔ · retrieval + answer experiments in Langfuse ✔ · baseline recorded and `make eval` gating ✔ (local) · review decisions as scores ✔ · CI green ✔.
- **Next:** Phase 3 plan — retrieval (synonyms, rerank, context) against this baseline; first targets: the limitations misses (lim-02/03/07/09), mv-01, mv-11, and total latency.

## 2026-09-25 · Phase 2 · 2.6 Review decisions logged

- **What:** after every review decision, `review.log_decision` posts Langfuse scores on the answer's trace — `review_decision` (categorical), `time_to_review_s`, `edit_distance` (1 − difflib ratio, approved/edited; the note as comment), `review_reason` (rejections). Edited and rejected answers are appended once per answer id to `evals/gold_candidates.jsonl` for manual promotion. A logging failure never fails the decision (logged instead).
- **Validated:** tests red first → 203 passed. Built-in browser as reviewer: approved #8, rejected #10 (`missing_authority`) → Langfuse: #8 `review_decision=approved, edit_distance=0.0, time_to_review_s=930`; #10 `review_decision=rejected, review_reason=missing_authority, time_to_review_s=35`; #10 in the candidates file.
- **Bug found and fixed:** review tests without the scoring fixture wrote test answers (ids 9, 12) into the repo's candidates file → autouse fixture points every test at a temp file; leaked lines removed; file hash unchanged by `make test`.
- **Next:** 2.5 baseline + CI after the user's gold and judge spot checks and the gate decision.

## 2026-09-25 · Phase 2 · 2.4 Answer experiment + judge + gate calibration

- **What:** `evals/answers.py` (facts_covered, refusal_correct, verified_rate, gate_tradeoff; `judge_answer` — one gemini-3.5-flash-lite call per answer grading each claim against its own quote plus faithful / gives_advice; malformed output → `judge_error`, not dropped). `scripts/eval.py answers`: full pipeline per gold item without DB writes (retrieve → gate → gemini-3.7-flash → verify → subsection pinpoints), code + judge evaluators, local report with gate trade-off and a judge spot-check sample.
- **Validated:** tests red first → 14 new (200 total). Run → [Langfuse dataset run](https://us.cloud.langfuse.com/project/cmuhr5jjm053rad0chpar3j5x/datasets/cmuhu62p505bsad0cefumvo3x/runs/f9559fe4-7f54-4193-9e3d-6ef0dca1f486), 0 judge errors.
- **Baseline (62 in scope / 15 out of scope):** has verified claim 0.919 · verified claim rate 0.994 · facts covered 0.847 · **citation supported (judge) 0.959** (target ≥ 0.95) · faithful 0.912 · no advice 1.000 · in-scope not refused 0.919 · **out-of-scope refused 0.933** (target ≥ 0.90; the miss, oos-06 CRA tax, ended `unverified` — nothing released, but not a clean refusal) · latency p50 / p95: sources 313 / 553 ms, total 3.5 / **9.2 s** (target < 8 s; 2-attempt `unverified` items and concurrency 4 inflate it). Limitations again weakest (0.6 has-verified / facts).
- **In-scope refused (unverified):** mv-11, lim-02, lim-03, lim-07, lim-09 — the same items retrieval missed.
- **Gate trade-off (best distance):** 0.30 → refuses 7/15 out-of-scope, 0 in-scope; 0.28 → 10/15, 1 in-scope; 0.26 → 11/15, 3 in-scope; current 0.35 → 0/15. Proposed 0.30 (saves model calls, no false refusals); change pending user OK.
- **Judge spot check:** random 10 — main session agrees 10/10; the 7 judge rejections — agrees with 5 (claims adding unquoted detail), disagrees with 2 (mv-06: too strict on a rule stated without its exception / a quote starting with "unless"). **User spot-check pending** before the baseline is recorded.
- **Next:** 2.6 review decisions as scores; then 2.5 baseline + CI once the gold and judge spot checks are approved.

## 2026-09-25 · Phase 2 · 2.3 Retrieval experiment (baseline)

- **What:** `evals/metrics.py` (a hit matches an expected pinpoint in the same law when either contains the other; recall@8 = any expected in top 8; MRR), `evals/langfuse_io.py` (dataset `ontario-injury-gold`, items keyed by gold id → idempotent), `scripts/eval.py retrieval` (Langfuse `run_experiment` over the dataset, real embedding + `retrieve`, item evaluators recall@8/mrr; local copy in `evals/runs/`, gitignored).
- **Validated:** metric tests red first → 186 passed. Run → [Langfuse dataset run](https://us.cloud.langfuse.com/project/cmuhr5jjm053rad0chpar3j5x/datasets/cmuhu62p505bsad0cefumvo3x/runs/2e5590b2-e6ae-489a-8387-0d61cb87af60). Re-upload → 77 items, 0 new.
- **Baseline (62 in-scope items):** recall@8 **0.855**, MRR **0.601**. By topic: city-claims 1.000 / 0.917 · slip-and-fall 1.000 / 0.762 · dog-bites 0.900 / 0.395 · procedure 0.818 / 0.611 · motor-vehicle 0.818 / 0.470 · **limitations 0.600 / 0.467**.
- **Misses (9):** lim-02 (discovery, s. 5), lim-03 (presumption), lim-07 (mediation suspends), lim-09 (adding a defendant), mv-01 (tort threshold), mv-11 (LAT application time), dog-09 (court orders), proc-02 (contributory negligence), proc-07 (serving a statement of claim).
- **Gate data:** best vector distance in scope 0.119–0.286 (median 0.194), out of scope 0.201–0.348 (median 0.288) — overlapping; the 0.35 gate refuses none of the 15. Calibration in 2.4.
- **Next:** 2.4 answer experiment + judge + gate calibration.

## 2026-09-25 · Phase 2 · 2.1 Gold set v1

- **What:** a subagent drafted 77 items from DB text (62 in scope across 6 topics, 15 out of scope incl. look-alikes: Alberta/BC/Quebec/US versions of in-scope questions, family property, rent, a 401 speeding ticket). `evals/gold.py` validates: required fields, unique ids, topics, expected pinpoints exist, every fact appears in an expected section's text (normalized), out-of-scope items have no pinpoints and `must_refuse`. Redundant parent pinpoints dropped (115 → 68) since metrics treat a section and its subsections as matching.
- **Validated:** validator tests (13) → `check_gold.py` → 77/77 valid (city 10, dog 10, limitations 10, motor-vehicle 11, procedure 11, slip 10, out-of-scope 15). Random 10 verified online at the user's request against official e-Laws text (current to 2026-09-23; read via the ontario.ca legislation API the e-Laws page itself uses): 9/10 valid with exact quotes; changed mv-01 (+ Insurance Act s. 267.5(7), the deductible) and proc-06 (+ WSIA s. 28(2), Schedule 2 employers). Still 77/77 valid. 2.3/2.4 numbers predate these two edits; 2.5 reruns both before recording the baseline.

## 2026-09-25 · Phase 2 · 2.2 Langfuse tracing on `/ask`

- **What:** `langfuse` 4.15.6. `app/tracing.py`: off unless `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` are set (one log line either way); `observe()` nests spans under the current trace. `/ask` trace: `ask` → `embed_query`, `retrieve` (fused top 8 with RRF scores and distances), `generate` (generation with prompt, output, attempt, token usage from Vertex `usage_metadata`), `verify` (kept / dropped with reasons), `store`. `answers.trace_id` saved; the review queue shows "View trace". `make api` / launch config load `.env` via `uv run --env-file`; pytest clears the keys; `make e2e` runs without them.
- **Validated:** tracing tests red first (fake Langfuse client) → 177 passed; `make e2e` 5/5 with tracing off. Real `/ask` (answer 8) → trace in Langfuse Cloud with SPAN ask/embed_query/retrieve/verify/store + GENERATION generate `{input: 3075, output: 328, thinking: 0}`; `auth_check` True; trace id stored on the row.
- **Next:** 2.1 gold set (draft in progress by a subagent), then 2.3 retrieval experiment.

## 2026-09-25 · Phase 1 follow-up · Small fixes + Playwright

- **What:** (1) Toronto by-laws: `pdftotext -layout` — default reading order emitted label columns ("A. B. C.") apart from their paragraphs in 575 labelled items; layout mode keeps each label with its text (parser v3, footers with page + date on one line handled). (2) Claims are pinned to the subsection that holds the quote (`pinpoint_claims`: s 42 → s 42(6)); the draft's citation lines and the chips use it. (3) Playwright (`@playwright/test` 1.63, Chromium headless shell 94 MB): `make e2e` starts its own API with `AI_FAKE=1` (deterministic fake model: embeds the best keyword match, quotes the first passage — retrieval, gate and quote verification still run for real) on :8001 and the web app on :3001 (`NEXT_DIST_DIR=.next-e2e`, since Next allows one dev server per build dir); `turbopack.root` pinned. Specs: library → law → section (text, provenance, official link, copy citation read back from the clipboard); Toronto excerpt ≤ 320 chars + toronto.ca link; unknown section 404; ask → reviewer approves → researcher sees "Reviewed by" → citation panel highlights the quote, focus on Close, Esc closes; researcher can't see the queue; edit without a note shows the inline error.
- **Validated:** tests red first for each fix → 160 Python tests; `make e2e` **5/5 passed** (12 s); `tsc` clean; § 743-44 now "A. An officer …" and 0 sections with stacked labels; section counts still equal each chapter's TOC; 95 chunks re-embedded (6.5 s). Real `/ask` on the sidewalk-notice question → claims cited as s 42(6), s 42(7), s 42(8).
- **Next:** write `docs/phase-2-plan.md` (gold set + Langfuse Cloud evals) for approval.

## 2026-09-25 · Phase 1 · 1.10 Ask and Review pages — Phase 1 complete

- **What:** `/ask` (form with pending state and inline errors; no-advice notice), `/answers/[id]` (researcher: "Awaiting review" + sources; after approval: final answer, citation chips, "Reviewed by … on …", "(edited by reviewer)"; after rejection: the reason), `/review` (reviewer only: risk flags, draft, claims beside verified quotes, dropped claims, approve / edit with required note / reject with reason). Header role switch (cookie → `X-Demo-User`, labelled demo). Citation chips open a side panel that loads the section through the API (excerpt rule enforced) and highlights the quote; focus moves to Close, Esc closes. Server Actions for ask/review/role; a small renderer for our draft markdown (no new dependency). Playwright not added — the flow was run in the built-in browser instead, as the user asked.
- **Validated (built-in browser, real Vertex):** researcher asked "I tripped on a broken sidewalk in Toronto … how soon must I give the City written notice?" → `/answers/5` "Awaiting review" + 8 sources (COTA s. 42 first), no draft → switched to reviewer → `/review` listed 4 (BC refusal flagged first); #5 draft: COTA s. 42 — written notice to the clerk within 10 days + reasonable-excuse rule, 3/3 verified quotes → Approve → queue 3 → switched to researcher → released answer with 3 chips and "Reviewed by Demo Reviewer on September 25, 2026" → chip opened s. 42 with the exact quoted sentence highlighted. DB: answer 5 `approved`, asked_by Demo Researcher, reviewed_by Demo Reviewer, 3 claims. Crawl still **3,282/3,282** (p95 58 ms). `/ask`, `/review`, `/answers/5` 200; unknown answer 404. `tsc` clean; 156 Python tests pass.
- **Fixed during validation:** "reviewed on" showed the UTC date → formatted in America/Toronto.
- **Known issues:** § 743-44 snippet starts "A. B. C." (empty lettered items in the PDF); chips for claims in the same section have identical labels; a successful clipboard copy is still unverified (blocked in background tabs).
- **Phase 1 exit:** every section browsable (3,282/3,282) ✔ · one reviewed answer with a verified quote (answer 5) ✔.
- **Next:** Phase 2 — gold set + Langfuse Cloud experiments in CI; review decisions logged; fix the LA s. 4 retrieval gap measured against the baseline.

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
