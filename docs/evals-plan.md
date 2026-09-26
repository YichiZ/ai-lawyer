# Eval suite plan: production readiness

**Goal:** before real users, measure the failure modes that would hurt a researcher: wrong pinpoints, advice, invented
authority, brittle retrieval, broken navigation and bad definitions. Today's evals (`make eval`) cover retrieval
recall, answer quality on the gold set, and summaries. They do not cover these.

**Principles**
- **Code before judges.** Deterministic checks wherever possible. An LLM judge is used only where meaning must be
  read, and always with a different model from the one that wrote the text (Flash-Lite judges Flash).
- **Every eval has a threshold, chosen before it runs.** A miss is a finding: an issue is filed, and the threshold is
  not lowered to pass.
- **Versioned datasets** in `evals/data/*.jsonl`. Each item has an id, a category and its expected behaviour, and is
  checked against the corpus where it references it.
- **One runner:** `uv run --env-file .env -m scripts.eval_suite [name ...]`. Results go to `evals/runs/<ts>-suite-*.json`
  and a table.

## The suite

| # | Eval | Question it answers | Data | Scoring | Threshold |
|---|---|---|---|---|---|
| 1 | **pinpoint** | Does each citation point at the provision that holds its quote? | gold in-scope questions (62) → fresh answers | code: the quote is inside the cited section/subsection text; "precise" = the narrowest provision that holds it | precision ≥ 0.98 |
| 2 | **search** | Do citation jumps and plain-word search land on the right law? | `search.jsonl` (≈ 40): citation forms, case citations, everyday words | code: first suggestion URL; expected law in /search top 3 | jump ≥ 0.95, hit@3 ≥ 0.90 |
| 3 | **safety** | Does the system refuse to advise, resist injection, and refuse out-of-scope questions? | `safety.jsonl` (≈ 30): advice-seeking, fact-specific, injection, out-of-scope | code (dollar/date regex, canary string, status) + Flash-Lite judge for advice; also whether the review queue flags it | no advice 1.00, injection resisted 1.00, out-of-scope refused ≥ 0.90; flagged reported |
| 4 | **abstention** | When the law isn't in the library, does it say so instead of inventing authority? | `abstention.jsonl` (≈ 15): real laws outside the corpus | code: `not_found`, or a draft whose prose names no statute absent from its cited sources | ≥ 0.90 |
| 5 | **robustness** | Does retrieval hold up when a question is reworded (lay, legal, typos)? | `paraphrases.jsonl`: 12 gold questions × 3 variants | code: recall@8 per variant vs the original; top-8 overlap (Jaccard) | variant recall ≥ 0.90; overlap reported |
| 6 | **glossary** | Are glossary definitions real definitions, faithful to their source? | all glossary terms | code: non-answer patterns; Flash-Lite judge vs the defining section | non-answers ≤ 2 %, faithful ≥ 0.95 |

Existing evals stay as they are: `retrieval`, `answers`, `summaries` (the gate) and `caselaw` (not gated).

**Cost:** about 110 gemini-3.7-flash generations and 200 Flash-Lite calls, under $1.

## Iterations
1. **Scoring functions with unit tests** (`evals/suite.py`). Accept: each scorer has a passing and a failing case.
2. **Datasets.** Accept: every referenced slug and pinpoint exists in the corpus (validated at load).
3. **Runner and first run.** Accept: all 6 run to completion (no failed items), and results are recorded with
   thresholds in `docs/evals.md`.
4. **Evaluate.** Each miss gets a root cause and an issue, and the plan to make the suite a gate is written down.

**Stop if** a run would cost more than $3 or needs a new dependency.
