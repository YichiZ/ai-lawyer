# Phase 3 plan — better retrieval, measured step by step

Phase exit (from `docs/design.md`): typeahead, synonyms, hybrid, rerank, context — **each step's eval delta recorded**.

Starting line: `evals/baseline.json` (recall@8 0.855, MRR 0.602, has verified claim 0.919, citation supported 0.966,
faithful 0.930, out-of-scope refused 0.933; total latency p95 9.2 s vs the 8 s target). Known misses: lim-02, lim-03,
lim-07, lim-09, mv-01, mv-11, dog-09, proc-02, proc-07.

Rules for every retrieval iteration:
- Change one thing; run `scripts/eval.py retrieval` (cheap, deterministic) for the delta, then `make eval` before
  keeping it. A step is **kept only if** recall@8 or MRR improves and no metric regresses beyond tolerance; otherwise it
  is reverted and the negative result recorded.
- Record per step: recall@8, MRR (overall + limitations/motor-vehicle), items fixed/broken, latency added, cost.
- When a kept step changes results, re-record the baseline deliberately (`make eval-baseline`) and commit it.
- The gold set is not tuned to the system: no editing questions to make a step look better.

Same format as before: **Accept**, **Tests**, **Validate**, **Stop if**.

---

## 3.1 Miss analysis (no code change to retrieval)

**Accept**: for each of the 9 misses, the rank of the expected pinpoint in the keyword list, the vector list and the
fused list (or "absent from top 50"), and the query terms; a one-line cause per miss (vocabulary gap, keyword noise
drowning a good vector hit, chunk too long/diluted, wrong section boundary). This decides the order of 3.2–3.5.

**Validate**: table in `docs/iterations.md`.

---

## 3.2 Synonym expansion (keyword side only)

**Accept**: `synonyms` table (~50 curated rows, novice → legal terms, e.g. "sue" → "proceeding", "claim"; "time limit"
→ "limitation period"; "partly to blame" → "contributory negligence"); applied to the keyword query only (the vector
query is unchanged); rows loaded from a committed file; no rows written from gold questions verbatim.

**Tests**: expansion function (word boundaries, multi-word phrases, no double expansion); keyword query uses it.

**Validate**: retrieval delta; `make eval`; list of misses fixed/broken.

---

## 3.3 Fusion tuning

**Accept**: try, one at a time: weighted RRF (vector weight > keyword), keyword AND-then-OR fallback instead of pure OR,
candidate depth 50 → 100. Keep the best single change only if it beats 3.2.

**Tests**: weighted RRF on fixed rankings.

**Validate**: retrieval delta per variant (table), then `make eval` for the kept one.

---

## 3.4 Listwise rerank

**Accept**: gemini-3.5-flash-lite ranks the fused top 30 (ids + first ~120 words) in one JSON call; keep top 8. Rerank
failures/timeouts fall back to the fused order (logged, traced). The grounding gate moves to the rerank signal only if
the gold data shows it separates in/out of scope better than distance (else keep 0.30).

**Tests**: rerank parser (valid, missing ids, unknown ids, malformed → fallback); fallback path.

**Validate**: retrieval + answer deltas; latency added (sources p95 must stay < 2 s); cost per question.

**Stop if** sources p95 exceeds 2 s — cut candidates before changing models (design doc rule).

---

## 3.5 Chunk context

**Accept**: gemini-3.5-flash-lite writes 1–2 sentences placing each chunk in its law (document outline in the prompt;
context caching if available on Vertex for this model), stored in `chunks.context`, feeding `tsv` and the embedding
input; chunk text itself unchanged (quote verification unaffected). Re-embed only changed chunks. Cost estimate shown
before the full run (~3.4k chunks).

**Tests**: context prompt builder; idempotency (unchanged chunk → no new context call, no re-embed).

**Validate**: retrieval + answer deltas; cost and time of the run.

**Stop if** the estimated cost exceeds $5 — ask first.

---

## 3.6 Answer latency

**Accept**: total p95 < 8 s on an unthrottled run. First measure where time goes (traces: embed, retrieve, rerank,
generate per attempt, verify); likely levers: the second `unverified` attempt, prompt size (8 passages), thinking
level. Change only what the traces point to.

**Validate**: latency table before/after; `make eval` shows no quality regression.

---

## 3.7 Search and typeahead

**Accept**: `GET /suggest?q=` (pg_trgm on titles, headings; citation patterns like `s. 4`, `2024 ONCA 123` jump
straight to a section) and `GET /search?q=&type=` (hybrid retrieval grouped by law); a search box in the header
(`/` shortcut) and a results page; question-shaped queries offer "Ask this".

**Tests**: citation-pattern parser; suggest ranking; one integration test per endpoint; Playwright flow
search → section.

**Validate**: `/suggest` p95 < 100 ms locally; e2e green in CI.

---

**Phase exit**: every step's delta recorded (kept or reverted) · baseline re-recorded after the last kept change ·
search + typeahead shipped · total latency p95 < 8 s, or the remaining gap explained.
