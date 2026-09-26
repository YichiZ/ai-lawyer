# Phase 2 plan — evals, tracing and the baseline

Phase exit (from `docs/design.md`): gold set + Langfuse experiments in CI; review decisions logged; **baseline recorded**.

Same rules as Phase 1: each iteration lists **Accept**, **Tests**, **Validate**, **Stop if**; done only when every Accept line is shown true in output recorded in `docs/iterations.md`. Common to every iteration: `check_vertex.py` 6/6 at session start, `make test` and `make e2e` green, no secrets in the diff, dependencies approved before adding.

Scope notes:
- Case-law questions (~25 in the design) wait for Phase 5, when decisions are in the corpus. Phase 2's gold set is statutes/by-laws + out-of-scope.
- No retrieval or prompt changes in Phase 2 — it measures the Phase 1 system as-is. Fixes (e.g. Limitations Act s. 4 missing for "how long to sue") are Phase 3, judged against this baseline.
- Langfuse Cloud (US) via the keys in `.env`. Everything must also run with Langfuse disabled (no keys → no-op), so tests and `make e2e` never need network.

---

## 2.1 Gold set v1

**Accept**
- `evals/gold.jsonl` in the repo, ~75 items: ~60 in-scope questions across the 5 topic guides + by-laws, ~15 out-of-scope (other provinces, criminal, family property, immigration, tax…).
- Each in-scope item: `id`, `question` (everyday and legal wording mixed), `topic`, `expected` = list of acceptable `{slug, pinpoint}` (section or subsection), `facts` = 1–3 short strings the answer must convey (e.g. "10 days", "city clerk").
- Automated check: every expected pinpoint exists in the DB, and each fact string appears in at least one expected section's text (whitespace/case-normalized) — so the gold answers are grounded in the official text, not memory.
- Out-of-scope items: `expected: []`, `must_refuse: true`.
- A subagent drafts candidates; the main session verifies each against the DB; the user spot-checks a random 10 (shown as a table) before it counts.

**Tests**: loader/validator for the file format (required fields, unique ids, pinpoints exist, facts grounded).

**Validate**: `uv run scripts/check_gold.py` → `75/75 valid`, counts by topic; spot-check table shown.

**Stop if** a topic has fewer than 8 groundable questions (tell the user rather than pad it).

---

## 2.2 Langfuse tracing on `/ask`

**Accept**
- `langfuse` Python SDK added (asks first). One trace per `/ask` with spans: `embed_query`, `retrieve` (keyword + vector ids, fused top 8, best distance), `generate` (model, prompt/response, token usage), `verify` (kept / dropped with reasons), `store`.
- `answers.trace_id` saved; the review page links to the trace.
- Keys only from the environment; missing keys → tracing off with one startup log line, app unchanged.
- Question text and public law text only are sent; no user identifiers beyond the demo role name.

**Tests**: tracing disabled path is a no-op (existing tests unchanged); a fake tracer records the expected span names and attributes.

**Validate**: one real `/ask` → trace visible in Langfuse Cloud with the 5 spans and token usage; `trace_id` on the row; `make test` / `make e2e` pass with no keys set.

---

## 2.3 Retrieval experiment

**Accept**
- `scripts/eval.py retrieval` uploads the gold set as Langfuse Dataset `ontario-injury-gold` (idempotent: items keyed by gold `id`, updated in place) and runs an Experiment calling the real retrieval (`retrieve`) per item.
- Code evaluators per item: `recall@8` (any expected pinpoint — or its parent section — in the fused top 8), `mrr`; aggregates per run and per topic; also best vector distance recorded per item.
- Local copy of every run in `evals/runs/<timestamp>-retrieval.json` (gitignored) and a printed summary table.

**Tests**: recall/MRR functions on hand-made rankings (incl. subsection-vs-section matching); dataset upsert idempotency with a fake client.

**Validate**: run → experiment visible in Langfuse; summary printed; rerun upload → 0 new dataset items.

---

## 2.4 Answer experiment + LLM judge + gate calibration

**Accept**
- `scripts/eval.py answers` runs the full pipeline (retrieve → gate → generate → verify) per item without writing `answers` rows.
- Code evaluators: `verified_claim_rate` (verified / proposed), `has_verified_claim`, `refusal_correct` (out-of-scope refused; in-scope not refused), `facts_covered` (fact strings present in the answer, normalized), latency (sources / total), tokens.
- LLM judge (judge ≠ answer model — `gemini-3.5-flash-lite` by default, see Stop if): per claim, "does the quoted text support this claim?" → `citation_supported`; per answer, "is it faithful to the quotes and free of advice/outcome predictions?" → `faithful`. Judge prompt, model and version stored with the score.
- Gate calibration report: best-distance distribution for in-scope vs out-of-scope items; proposed `GATE_MAX_DISTANCE` with the refusal/false-refusal trade-off. The constant changes only if the user agrees.

**Tests**: evaluators on fixed inputs; judge wrapper parses/validates the JSON verdict and handles a malformed one (score recorded as `judge_error`, not dropped).

**Validate**: full run on the gold set → per-metric table; judge agreement spot-check: the user reviews 10 judged claims.

**Stop if** Flash-Lite judge disagrees with the user on > 2 of 10 spot checks — then propose a stronger judge before recording the baseline.

---

## 2.5 Baseline + CI

**Accept**
- `evals/baseline.json` (committed): metrics from 2.3 + 2.4 with run ids, model names, corpus hash (sorted document sha256s) and gold-set hash.
- `make eval` = retrieval + answer experiments, compared with the baseline: fails if any quality metric drops > 2 points, or if the corpus/gold hash differs from the baseline's (then the baseline must be re-recorded deliberately).
- GitHub Actions: on every push/PR — `make test` (Postgres service) and `make e2e` against a small committed fixture corpus (3 laws with their chunks and embeddings as a SQL fixture, so CI needs no Vertex and no downloads). `make eval` job runs on demand / nightly once Vertex auth for CI exists.
- Fixture corpus is generated by a script from the dev DB, so it can be refreshed.

**Tests**: baseline comparison logic (drops, improvements, hash mismatch); fixture loader.

**Validate**: CI green on a PR; `make eval` locally → "no regression vs baseline"; a deliberately broken retrieval (e.g. top 2 instead of 8, not committed) → `make eval` fails with the metric named.

**Stop if** CI Vertex auth needs Workload Identity Federation in GCP — that is an IAM change on the user's project; ask the user to set it up (steps provided), and until then run `make eval` locally only.

---

## 2.6 Review decisions logged

**Accept**
- On every review decision, a Langfuse score on the answer's trace: `review_decision` (approved / edited / rejected), `review_reason`, `edit_distance` (draft vs final, normalized), `time_to_review_s`.
- Edited and rejected answers are appended to `evals/gold_candidates.jsonl` (question, draft, final/reason) for later promotion into the gold set — never automatically.
- Weekly numbers available from Langfuse: approval rate, edit rate, median time to review.

**Tests**: decision → score payload (fake client); edit distance function; candidate file append is idempotent per answer id.

**Validate**: approve one and reject one in the UI (built-in browser) → both scores visible on their traces; rejected one in the candidates file.

---

**Phase exit**: gold set valid (2.1) · retrieval + answer experiments in Langfuse (2.3–2.4) · `evals/baseline.json` recorded and `make eval` gating (2.5) · review decisions as scores (2.6). Record the baseline numbers in `docs/iterations.md`; they become Phase 3's starting line.
