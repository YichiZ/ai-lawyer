# Phase 4 plan — guides, summaries, glossary, design pass

Phase exit (from `docs/design.md`): 5 topic guides, summaries, glossary, visual design pass — **summaries ≥ 95%
faithful, reading grade ≤ 10; Lighthouse green**.

Pre-approved (2026-09-26): `@axe-core/playwright`, `@lhci/cli`, Radix UI primitives; LLM batch spend within the
$25 total. Same rules: **Accept / Tests / Validate / Stop if**; `make test`, `make e2e`, `make eval` green.

---

## 4.1 Plain-language section summaries

**Accept**: gemini-3.7-flash writes a grade-10 summary per section with substantive text (skip `[blank]`, repealed,
omitted), stored in `sections.plain_summary` with `summary_source_hash` (section text hash + prompt version) so only
changed sections are redone. Rules in the prompt: state the rule, keep legal terms (with a short gloss), no advice,
no outcome predictions, no computed dates. Toronto by-law summaries allowed (our own words), text still excerpt-only.
Section page shows the summary beside the official text, labelled "AI-written, checked against the official text".

**Tests**: skip rules; hash idempotency; API returns `plain_summary`; page renders the label.

**Validate**: run over all sections (cost estimate printed first); rerun → 0 calls.

**Stop if** the estimate exceeds $10.

## 4.2 Summary evals

**Accept**: `scripts/eval.py summaries`: 50 sampled summaries (fixed seed) — LLM-judge faithfulness vs the official
text (judge ≠ writer: Flash-Lite), code-scored reading grade (Flesch–Kincaid, stdlib implementation) ≤ 10, legal
terms preserved; metrics added to `evals/baseline.json` and the gate.

**Tests**: grade function on known passages; judge parser.

**Validate**: faithful ≥ 0.95 and mean grade ≤ 10, or iterate the prompt (4.1) and rerun; spot-check 5 by hand.

## 4.3 Glossary

**Accept**: ~100 terms (occupier, limitation period, discoverability, contributory negligence, joint and several,
threshold, …) with plain definitions written by Flash from the defining statutory text where one exists (with the
source pinpoint), else marked "general legal term"; `glossary_terms` table; `/glossary` page; terms in section text
get a Radix tooltip with the definition and a link.

**Tests**: term matcher (whole words, longest match first, not inside other words); API; tooltip keyboard access.

## 4.4 Topic guides

**Accept**: 5 guides (motor vehicle, slip and fall, City of Toronto claims, dog bites, limitation periods) at
`/guides/[slug]`: deadlines first (as rules, with pinpoints — no calculator), elements, laws that apply (linked),
scoped Ask box. Drafted by the answer pipeline from retrieved sections with verified quotes, then stored as
`guides` rows with `reviewed_by` / `reviewed_at` — **each guide goes through the review queue** before it shows.
Home page: 5 topic cards + search + recent reviewed answers.

**Tests**: guide API; unreviewed guides hidden from researchers; Playwright topic → deadline → section.

## 4.5 Design and accessibility pass

**Accept**: Radix Tooltip/Dialog for glossary and the citation panel (replacing the hand-rolled panel); ⌘K palette
opening the search box; 150 ms fades with reduced-motion respected; print stylesheet checked; axe in every
Playwright flow with 0 violations; Lighthouse CI in GitHub Actions on home, a law page, a section page and a guide:
LCP < 1.5 s (simulated 4G), < 100 KB JS on law pages, CLS < 0.05, accessibility 100.

**Tests**: axe assertions in e2e; Lighthouse CI budgets.

**Validate**: CI green with Lighthouse reports attached.

---

**Phase exit**: summaries faithful ≥ 0.95, grade ≤ 10 (recorded) · 5 reviewed guides live · glossary live ·
axe 0 violations · Lighthouse budgets green in CI · baseline re-recorded.
