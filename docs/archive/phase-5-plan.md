# Phase 5 plan — case law (ONCA + SCC), citation graph, case pages

Phase exit (from `docs/design.md`): ONCA + SCC decisions, citation graph, case pages — **case-law gold questions pass**
(reported as "unverified": not expert-checked, not a CI gate — user decision 2026-09-25).

Pre-approved (2026-09-26): download A2AJ `ONCA/train.parquet` (183.5 MB) + `SCC/train.parquet` (365.3 MB); LLM batch
spend within the $25 total (≈ $10 used by end of Phase 4, so ≈ $15 left — every batch job prints an estimate first and
stops if it would exceed what remains). Same loop and rules as before.

Known gap to say in the UI: A2AJ has no Ontario Superior Court (trial) decisions; CanLII full text is not used.

---

## 5.1 Fetch and inspect

**Accept**: both files in `input/a2aj/` with manifest lines (sha256 verified via Hugging Face etag; rerun downloads 0
bytes); a schema report: columns, row counts, date range, how paragraphs and citations are represented, licence field.

## 5.2 Injury filter

**Accept**: keep decisions that cite a v0 statute (from A2AJ citation data if present, else regex on the text for the
12 statutes' names/citations) or match injury terms (negligence, occupier, limitation period, accident benefits, dog
bite, …) with a minimum hit count; report counts per court and year, with 20 random kept and 20 random dropped titles
for a sanity check. Target: a few thousand decisions; if far more, tighten before loading.

## 5.3 Load decisions

**Accept**: `documents` rows (kind `decision`, court, neutral citation, date, url, licence); `sections` = numbered
paragraphs (pinpoint `para-45`, display "para 45"), text kept exactly; chunks = windows of whole paragraphs (~500
tokens) so quotes verify; embeddings (estimate first). No chunk context for decisions in this phase (cost). Loader is
idempotent (hash per decision), one transaction per decision.

**Tests**: paragraph splitter on real-looking text (numbered, unnumbered, headnotes); pinpoint/display; windowing
keeps whole paragraphs; McGill case citation (*Smith v Jones*, 2024 ONCA 123 at para 45).

## 5.4 Citation graph

**Accept**: `citations` table (citing decision → cited decision or statute section, with pinpoint when stated);
extraction from A2AJ citation data plus regex for neutral citations and "s. 4 of the Limitations Act, 2002" /
"Limitations Act, 2002, s. 4" patterns; section pages show "Cited by N decisions" with links; case pages show cites
and cited-by.

**Tests**: regex extraction on fixtures (neutral citations, statute + section in both orders, ranges).

## 5.5 Case pages, search, retrieval

**Accept**: `/cases/[citation]` (plain summary, numbered paragraphs, cites / cited-by, source + licence, trial-court
gap note); `/suggest` jumps on `2024 ONCA 123`; search groups Laws · Cases; retrieval includes decisions with a small
authority boost (SCC > ONCA) measured on the gold set (kept only if it helps); plain decision summaries (facts,
outcome, why it matters) by gemini-3.5-flash-lite for the loaded decisions, estimate first, faithfulness judged on a
sample of 30.

## 5.6 Case-law gold and evals

**Accept**: ~25 case-law questions drafted from loaded decisions (grounded: expected paragraphs exist, facts appear in
them), tagged `unverified`; experiments report them as a separate group; statute baseline unaffected (gate unchanged).

---

**Phase exit**: decisions loaded and searchable · citation graph live on section and case pages · case pages ·
case-law gold group reported (unverified) · spend within budget · baseline re-recorded.
