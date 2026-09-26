"""Typeahead (/suggest) and grouped search (/search).

Typing a citation ("s. 4(1)", "OLA s 6.1", "r. 2.02", "§ 743-9") jumps straight to the section; anything else is
matched against law titles and section headings with pg_trgm.
"""
import re

import psycopg
from psycopg.rows import dict_row

from ingest.statutes import display_pinpoint

SUGGEST_LIMIT = 8
SEARCH_TOP_K = 20
BYLAW = re.compile(r"^\s*(?:§\s*)?(\d{3})-(\d+(?:\.\d+)?)\s*$")
CITATION = re.compile(
    r"^\s*(?P<law>.*?)[\s,]*(?<![a-z])(?P<kind>ss?|sections?|r|rules?)\.?\s*(?P<num>\d+(?:\.\d+)*)"
    r"(?P<subs>(?:\(\w{1,4}\))*)\s*$",
    re.IGNORECASE,
)
QUESTION_WORDS = ("how", "what", "when", "where", "who", "why", "which", "can", "could", "do", "does", "did", "is",
                  "are", "am", "should", "if", "will", "may", "must")
ABBREVIATIONS = {
    "la": "limitations-act-2002", "na": "negligence-act", "ola": "occupiers-liability-act",
    "dola": "dog-owners-liability-act", "ia": "insurance-act", "sabs": "statutory-accident-benefits-schedule",
    "hta": "highway-traffic-act", "cja": "courts-of-justice-act", "rcp": "rules-of-civil-procedure",
    "rules": "rules-of-civil-procedure", "fla": "family-law-act", "cota": "city-of-toronto-act-2006",
    "wsia": "workplace-safety-and-insurance-act-1997",
}


def parse_citation(q: str) -> tuple[str | None, str] | None:
    """(law hint or None, pinpoint slug) if q looks like a citation, else None."""
    if m := BYLAW.match(q):
        return None, f"{m.group(1)}-{m.group(2)}"
    m = CITATION.match(q)
    if not m:
        return None
    prefix = "r" if m.group("kind").lower().startswith("r") else "s"
    subs = "".join(f"-{s}" for s in re.findall(r"\((\w{1,4})\)", m.group("subs")))
    law = m.group("law").strip(" ,").lower() or None
    return law, f"{prefix}-{m.group('num')}{subs.lower()}"


def is_question(q: str) -> bool:
    words = q.strip().lower().split()
    return bool(words) and (q.strip().endswith("?") or words[0] in QUESTION_WORDS)


def _law_slugs(conn: psycopg.Connection, hint: str | None) -> list[str] | None:
    """Slugs a law hint refers to (abbreviation or closest title), or None for 'any law'."""
    if hint is None:
        return None
    if hint in ABBREVIATIONS:
        return [ABBREVIATIONS[hint]]
    row = conn.execute(
        "SELECT slug FROM documents WHERE word_similarity(%s, lower(title)) > 0.5"
        " ORDER BY word_similarity(%s, lower(title)) DESC LIMIT 1", (hint, hint),
    ).fetchone()
    return [row[0]] if row else []


def _section(r: dict) -> dict:
    return {"type": "section", "slug": r["slug"], "title": r["title"], "display": display_pinpoint(r["pinpoint"]),
            "heading": r["heading"], "url": f"/laws/{r['slug']}/{r['pinpoint']}"}


def suggest(conn: psycopg.Connection, q: str, limit: int = SUGGEST_LIMIT) -> list[dict]:
    cur = conn.cursor(row_factory=dict_row)
    if (citation := parse_citation(q)) is not None:
        hint, pinpoint = citation
        slugs = _law_slugs(conn, hint)
        rows = cur.execute(
            "SELECT d.slug, d.title, s.pinpoint, s.heading FROM sections s JOIN documents d ON d.id = s.document_id"
            " WHERE s.pinpoint = %s AND (%s::text[] IS NULL OR d.slug = ANY(%s)) ORDER BY d.title LIMIT %s",
            (pinpoint, slugs, slugs, limit),
        ).fetchall()
        return [_section(r) for r in rows]
    laws = cur.execute(
        "SELECT slug, title, citation FROM documents WHERE %s <%% lower(title)"
        " ORDER BY word_similarity(%s, lower(title)) DESC, title LIMIT 3", (q.lower(), q.lower()),
    ).fetchall()
    sections = cur.execute(
        "SELECT d.slug, d.title, s.pinpoint, s.heading FROM sections s JOIN documents d ON d.id = s.document_id"
        " WHERE s.kind = 'section' AND %s <%% s.heading"
        " ORDER BY word_similarity(%s, s.heading) DESC, d.title, s.sort_order LIMIT %s",
        (q, q, limit),
    ).fetchall()
    out = [{"type": "law", "slug": r["slug"], "title": r["title"], "display": r["citation"], "heading": None,
            "url": f"/laws/{r['slug']}"} for r in laws]
    return (out + [_section(r) for r in sections])[:limit]


def group_by_law(hits: list) -> list[dict]:
    """Retrieved hits (in rank order) grouped by law, groups ordered by their best hit."""
    groups: dict[str, dict] = {}
    for h in hits:
        s = h.source
        g = groups.setdefault(s["slug"], {"slug": s["slug"], "title": s["title"], "hits": []})
        g["hits"].append({"pinpoint": s["pinpoint"], "display": s["display"], "citation": s["citation"],
                          "snippet": s["snippet"], "url": s["url"]})
    return list(groups.values())
