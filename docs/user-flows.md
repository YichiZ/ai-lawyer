# User flows and acceptance criteria

Ten flows that define "working" for the demo. Each one is checked end to end: automated in Playwright where noted
(`make e2e-ci`, fixture corpus, fake model), and by hand on the full corpus with the real model (`make api` + `make web`).
Roles: **R** = Demo Researcher, **V** = Demo Reviewer.

## 1. Browse the library to a section (R)
Home → Laws → a law → a section.
- The law list is grouped by kind (statutes, regulations, Toronto by-laws, official web pages) and shows citation and section count.
- The law page shows the Part/section tree. Every section links to its page.
- The section page shows the official text with clause indents, the breadcrumb, previous/next links, the official link,
  "in force from" and the licence.
- The "In plain language" summary is labelled as AI-written and not legal advice.
- A copy-citation button copies the McGill citation (e.g. *Limitations Act, 2002*, SO 2002, c 24, Sched B, s 4).
- Glossary terms used in the section are listed, as is "Cited by N decisions" when there are any.
- *Automated:* `library.spec.ts`.

## 2. Toronto by-law excerpt rule (R)
Open a Toronto Municipal Code section.
- The page never shows more than a short excerpt (≤ 300 chars) and says why (City copyright).
- It links to the official PDF.
- The API also returns an excerpt only, so the rule does not depend on the UI.
- *Automated:* `library.spec.ts` (743-44), API tests.

## 3. Find a law by citation or everyday words (R)
Type in the header search box (`/` focuses it).
- Typeahead appears within 2 characters and can be driven by keyboard (↑/↓/Enter, Escape closes).
- "LA s. 4" or "limitations act s 4" jumps straight to the section; "2016 ONCA 585" jumps to the decision.
- A plain-words query ("slip and fall on ice") lists relevant laws grouped by law, each hit with a snippet and pinpoint.
- An empty or 1-character query shows guidance, not an error.
- *Automated:* `search.spec.ts`.

## 4. Ask a research question (R)
Ask page → question → answer page.
- Questions under 5 or over 1,000 characters are refused with a clear message.
- Sources appear within 2 s: laws first, then relevant decisions, each with its citation and a link.
- The answer shows "Awaiting review". The draft is never shown to a researcher before approval.
- Advice-seeking wording gets no advice in any released answer (no "you have a case", no values, no dates computed).
- *Automated:* `ask-review.spec.ts`.

## 5. Review and release an answer (V → R)
Switch to reviewer → Review queue → decide.
- The queue shows risky drafts first, each with its flags (dropped claims, not found, web fallback, failed).
- Each draft shows claims with verified quotes and source links, plus a trace link when tracing is on.
- Approve releases the draft unchanged. Edit needs revised text and a note. Reject needs a reason.
- Deciding twice gives a clear "already reviewed" message.
- The researcher then sees the released answer with citation chips (quote in a popover), "Reviewed by … on …", and "(edited)" when edited.
- A rejected answer shows the reason and still lists its sources.
- *Automated:* `ask-review.spec.ts`.

## 6. Not found → web fallback (R → V)
Ask something the library does not cover.
- The gate says the library has no close match and offers "Search the web instead" (opt-in, never automatic).
- The web draft is labelled "From the web, not our law library", lists its sources with domains, and goes to review
  flagged `web_fallback`.
- Out-of-scope questions (criminal, family, other provinces) are refused, not answered from the web by default.
- *Automated:* `web-fallback.spec.ts`.

## 7. Add an official web source to the library (V)
Review queue → web-fallback draft → "Add to library".
- Only sources on ontario.ca, canada.ca, ontariocourts.ca, scc-csc.ca and toronto.ca get the button. Others say why not.
- Clicking queues a job. "Check status" moves through the stages to "Added to the library — open".
- The new page appears in the law list and in search.
- A refused page (robots.txt, 404) ends as "Could not be added — reason" with no retries.
- *Automated:* `web-fallback.spec.ts` (queued); worker in pytest.

## 8. Read a decision (R)
From a section's "Cited by", or a case search result → case page.
- The case page shows the style of cause, neutral citation, court, date, plain summary (labelled AI) and numbered
  paragraphs with anchors (`#para-12`).
- It lists the laws cited (linked to sections), the cases cited and the cases citing it, plus the licence.
- It notes that trial-level (Superior Court) decisions are not in the corpus.
- *Automated:* `cases.spec.ts`.

## 9. Topic guides and glossary (R)
Home → a topic card → guide; header → Glossary.
- The home page shows the 5 topic guides with "N of M sections reviewed".
- A guide shows only reviewed sections. Deadlines come first, stated as rules, never computed dates. Unreviewed
  sections say so.
- The glossary lists terms A–Z. Each term has a plain definition and links to the sections that define or use it.
- *Automated:* partial (a11y scan of /glossary).

## 10. Accessible and resilient everywhere (R, V)
Every page, both themes, keyboard only.
- 0 axe violations (WCAG 2.2 AA) in light and dark modes, visible focus, skip link, targets ≥ 24 px.
- Unknown law, section, case or answer → a 404 page with a way back, not a crash.
- API down → a friendly "library is unavailable" message.
- Pages are usable at 375 px wide with no horizontal scroll.
- *Automated:* `a11y.spec.ts`, Lighthouse CI.
