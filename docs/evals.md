# Evals

Two layers:
1. **The regression gate** (`make eval`): retrieval, answers and summaries on the 62-question gold set, compared with
   `evals/baseline.json`. It fails on a drop of more than 2 points; LLM-judge metrics use a tolerance sized from
   their measured noise (below).
2. **The production suite** (`make eval-suite`): six evals that target the failure modes that would hurt a real
   researcher. The plan is in [evals-plan.md](evals-plan.md).

All evals run locally with Vertex AI through ADC. Results are saved to `evals/runs/`.

## Current regression gate (baseline 2026-09-27, mean of 3 runs)

| Metric | Value |
|---|---|
| retrieval recall@8 / MRR | 1.000 / 0.908 |
| answers: verified-claim rate · facts covered · citation supported · faithful (judge) · no advice | 0.995 · 0.970 · 0.947 · 0.892 · 1.000 |
| refusals: in-scope answered · out-of-scope refused | 1.000 · 1.000 (18 out-of-scope, #19) |
| section summaries: faithful · grade ≤ 10 | 0.973 · 0.46 |
| decision summaries (30-item judge) | faithful 0.967, grade 13.4 |
| case-law retrieval (unverified gold, not gated) | recall@8 0.857, MRR 0.587 |

### How the gate handles judge noise (#31)

- **Where the noise is.** Re-judging the same 71 drafts 5 times moves faithful by sd 0.007 (0.901–0.915) and
  citation support by sd 0.009. Across 10 full runs (new drafts each time) faithful has sd 0.029 (0.871–0.957) and
  citation support sd 0.016. Summaries faithful (fixed summaries, so judge only) has sd 0.015. Almost all the noise
  comes from the drafts, so averaging judge passes would not help. Averaging full runs does.
- **Baseline = mean of 3 full runs** (`make eval-baseline`, ~$1.5).
- **Tolerance = 2 sd of the difference of means**, using the measured per-run sd (`RUN_SD` in `evals/baseline.py`):
  `2·sd·√(1/n_gate + 1/n_baseline)`, never below 2 points. One gate run against a 3-run baseline allows 6.7 points for
  faithful, 3.7 for citation support and 3.5 for summaries faithful. `gate --runs 2` tightens faithful to 5.3. Code
  metrics (and no_advice, which has not varied) stay at 2 points. The old flat 5 points failed about 1 single-vs-single
  comparison in 9 on faithful by chance alone.
- **No ratchet.** `record` keeps the old value of a judge metric when the new mean is within noise (up or down), and
  refuses to write a drop beyond noise unless `--accept-drop`. Before, each re-record took one run's draw, and
  0.943 became 0.900 in #2.

## Production suite: first run (2026-09-26)

The 95 % intervals are Wilson intervals. With datasets this small, treat a single miss as a signal, not a rate.

| Eval | Result | Threshold | 95 % CI | Verdict | Issue |
|---|---|---|---|---|---|
| **pinpoint** precision (155 claims, 62 answers) | 0.929 → 1.000 (158 claims) after #1 | ≥ 0.98 | 0.88–0.96 → 0.976–1.00 | ✅ | #1 |
| **search** citation jumps (28) | 0.857 → 0.929 after #12 → 1.000 after #14, #20 | ≥ 0.95 | 0.69–0.94 → 0.88–1.00 | ✅ | #12, #14, #20 |
| **search** plain-words hit@3 (12) | 0.917 → 1.000 after #41 (/search reranked) | ≥ 0.90 | 0.65–0.99 → 0.76–1.00 | ✅ | #8, #41 |
| **safety** no advice (28) | 1.000 | 1.00 | 0.88–1.00 | ✅ | |
| **safety** injection resisted (6) | 1.000 | 1.00 | 0.61–1.00 | ✅ | |
| **safety** out-of-scope refused (10 → 13) | 0.900 → 1.000 in 4 runs after #19 (13/13) | ≥ 0.90 | 0.60–0.98 → 0.77–1.00 | ✅ | #19 fixed |
| **safety** advice-seeking questions flagged for the reviewer (12; 7 drafted) | 0.583 (0/7 drafts) → 1.000 (7/7 drafts `advice_seeking`, 5 `not_found`) after #7 | ≥ 0.90 | 0.76–1.00 | ✅ | #7 fixed |
| **abstention** no invented authority (15) | 1.000 | 1.00 | 0.80–1.00 | ✅ | |
| **abstention** abstained, grounded, or labelled as quoted by a decision (15) | 1.000 | ≥ 0.90 | 0.80–1.00 | ✅ | #18 |
| **abstention** secondary answers labelled and flagged (6) | 1.000 | reported | 0.61–1.00 | ✅ | #18 |
| **robustness** recall@8 on lay / legal / typo rewordings (36) | 1.000 | ≥ 0.90 | 0.90–1.00 | ✅ | |
| **robustness** top-8 overlap with the original question | 0.573 | reported | | ℹ️ | |
| **glossary** non-answers (85; was 19/81 = 0.235 before #4) | 0.000 | ≤ 0.02 | 0.00–0.04 | ✅ | #4 fixed |
| **glossary** faithful (85; was 0.968 among 62 real definitions) | 0.976 | ≥ 0.95 | 0.92–0.99 | ✅ | #4 fixed |

Cost of the run: about 105 gemini-3.7-flash drafts and about 110 Flash-Lite calls (under $1). Time: about 10 minutes.

## What the results mean

- **Safety holds.** Across 28 adversarial prompts (asking for advice, fact-specific questions, injection attempts,
  out-of-scope topics):
  - No answer gave advice, whether checked by code (outcome and valuation phrases, computed dates) or by the judge.
  - Every injection failed. Given a false premise ("pretend the limit is 10 years"), the model corrected it from the
    quote.
  - Quote verification means the model cannot invent a statute: 0 of 15 answers invented authority.
- **Citation precision is the biggest correctness risk.** 7 % of claims cite a subsection that does not contain their
  quote. For example, Insurance Act s. 267.5(1) is cited for quotes from (6) and (8), and DOLA s. 4(1) for quotes
  from (3) and (7). The quote itself is verified, but the pinpoint shown to the researcher is wrong. This is #1, now
  measured. Fixing it is a P0 before real users.
- **Out-of-library law is answered from secondary sources.** For 7 of the 15 laws we don't hold (Municipal Act s. 44,
  Health Insurance Act, Human Rights Code, and others), the draft states the statute's rule by quoting a decision that
  quoted it, sometimes years ago. The answer is grounded, but the researcher isn't told the statute isn't in our
  library, or that its wording may have changed (#18). The grounding gate passes because nearby law is close, e.g. the
  City of Toronto Act s. 42. **Fixed (2026-09-26):** such drafts now open with "Statute quoted in a court decision —
  not in our law library …", carry `flags.secondary_statute`, and sit first in the review queue. The metric counts a
  secondary answer only when it is labelled and flagged: 0.533 → 1.000 (6 secondary, all labelled; 9 abstained).
- **Navigation bugs are found in code, not by users.** The search eval found 4 broken jumps: case names go to `/laws`
  (#12), `rule 76` (#14), `s. 7 limitations act` in reverse order (#20). A web page outranks the Limitations Act for
  "how long to sue" (#8).
- **Retrieval is robust to rewording.** Recall stays at 1.0 on lay, legal and misspelled variants, even when the
  top-8 overlap with the original question drops to 0.07. Fusion plus rerank recovers the right provision.
- **Glossary is the weakest content.** 23.5 % of definitions are model non-answers ("The provided text does not
  define…"). Several more are narrowed to one source: "damages" is defined only as a dog owner's liability. **Fixed
  (2026-09-27, #4):** the builder checks every definition with the shared non-answer detector plus a source-reference
  check, retries once, and never stores a failure; a law's own definition wins over the curated section. 0 non-answers
  in 85 (6 core terms added); faithful 0.976–1.000 over 4 judge runs (only "city clerk" and "municipality" flagged,
  for adding a general role / "local government").

## How the scorers were checked

Every failing item was read by hand before being counted:
- **pinpoint:** all 11 misses are real (quote and cited subsection compared).
- **glossary:** all 19 non-answers are real. The keyword sweep found no missed ones. The judge scores "the text does
  not define X" as faithful, so faithfulness is reported over real definitions only.
- **abstention:** the first scorer called decision-grounded answers "unsourced", and its regex cut "Trespass to
  Property Act" short. The scorer now separates **invented** (0), **secondary** (7) and **grounded/abstained** (8).
  The threshold was not changed. Since #18 the detector lives in `app/authorities.py`, shared by the product and the
  eval, and `secondary` counts only if the draft is labelled and flagged (`secondary_labelled`). The label skips laws
  we hold (exact match on title, short name or citation, ignoring dots and the year), so it never says "not in our
  law library" about one. Re-run after the review fixes: same 1.000 / 6 of 6 labelled.
- **safety:** the advice drafts were read. They state rules (60-day snow-and-ice notice, 7-day SABS notice) and never
  compute a date from the user's facts. Since #7 the drafting call also returns `advice_seeking` (the question asks
  whether the asker has a case, what they'd get, what they should do, or their own deadline), stored in the answer
  flags; the reviewer sees "Asks for advice on their own facts" and the eval scores risk with the production
  `result_flags` → `risk_reasons` path.

## Taking it to production

1. **Gate on it.**
   - The pure-code parts need no model and can run in CI on the fixture corpus: search jumps, the pinpoint check on
     stored answers, and glossary non-answers.
   - The model-backed parts (safety, abstention, robustness) can run nightly or before release. They need Vertex AI
     in CI via Workload Identity Federation, which is not approved yet.
2. **Grow the datasets** until one miss is under 2 points: at least 50 per safety category, 50 out-of-library laws,
   and 100 search queries. Harvest real reviewer rejects and edits from `evals/gold_candidates.jsonl`.
3. **Calibrate the judges.** Have a human label 50 advice and glossary items, and track judge–human agreement (κ).
   LLM judges vary by up to 8 points between identical runs (Lessons learned).
4. **Put the suite in Langfuse** as datasets and experiments, next to the gate, so runs can be compared over time.
5. **Watch production:** sample reviewer decisions per risk flag, measure time-to-review, and alert on drift in the
   rejection rate.
