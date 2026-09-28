"""Typeahead (/suggest) and grouped search (/search).

Typing a citation ("s. 4(1)", "OLA s 6.1", "r. 2.02", "§ 743-9") jumps straight to the section; anything else is
matched against law titles and section headings (and subsection marginal notes) with pg_trgm.
"""
import re

import psycopg
from psycopg.rows import dict_row

from app.ask import retrieve, retrieve_web
from app.format import subtitle
from ingest.statutes import display_pinpoint

SUGGEST_LIMIT = 8
SEARCH_TOP_K = 20
BYLAW = re.compile(r"^\s*(?:§\s*)?(\d{3})-(\d+(?:\.\d+)?)\s*$")
PINPOINT = r"(?P<kind>ss?|sections?|r|rules?)\.?\s*(?P<num>\d+(?:\.\d+)*)(?P<subs>(?:\(\w{1,4}\))*)"
CITATION = re.compile(rf"^\s*(?P<law>.*?)[\s,]*(?<![a-z]){PINPOINT}\s*$", re.IGNORECASE)  # [law] s. 4
CITATION_LAW_LAST = re.compile(  # s. 7 limitations act, section 7 of the Limitations Act (issue #20)
    rf"^\s*{PINPOINT}[\s,]+(?:of\b\s*)?(?:the\b\s*)?(?P<law>[a-z].*?)?\s*$", re.IGNORECASE)
WHOLE_RULE = re.compile(r"^\d+(?:\.\d)?$")  # Rule 76, Rule 24.1 (a Part); subrules are 76.01, 24.1.01
CASE_CITATION = re.compile(  # anywhere in q: "Crinson v. Toronto (City), 2010 ONCA 44, at para 52", "[1982] 1 S.C.R. 175" (#63)
    r"(?<![\w\[])(?:(?P<year>\d{4})\s+(?P<court>ONCA|SCC)\s+(?P<num>\d+)"
    r"|\[(?P<ryear>\d{4})\]\s*(?P<vol>\d)\s*S\.?\s*C\.?\s*R\.?\s*(?P<page>\d+))\b"
    r"(?:\s*,?\s*(?:at\s+)?paras?\b\.?\s*(?P<para>\d+))?", re.IGNORECASE)
QUESTION_WORDS = ("how", "what", "when", "where", "who", "why", "which", "can", "could", "do", "does", "did", "is",
                  "are", "am", "should", "if", "will", "may", "must")
ABBREVIATIONS = {
    "la": "limitations-act-2002", "na": "negligence-act", "ola": "occupiers-liability-act",
    "dola": "dog-owners-liability-act", "ia": "insurance-act", "sabs": "statutory-accident-benefits-schedule",
    "hta": "highway-traffic-act", "cja": "courts-of-justice-act", "rcp": "rules-of-civil-procedure",
    "rules": "rules-of-civil-procedure", "fla": "family-law-act", "cota": "city-of-toronto-act-2006",
    "wsia": "workplace-safety-and-insurance-act-1997", "ma": "municipal-act-2001", "tpa": "trespass-to-property-act",
    "mvaca": "motor-vehicle-accident-claims-act", "caia": "compulsory-automobile-insurance-act",
    "hia": "health-insurance-act",
}


def parse_citation(q: str) -> tuple[str | None, str] | None:
    """(law hint or None, pinpoint slug) if q looks like a citation, else None."""
    if m := BYLAW.match(q):
        return None, f"{m.group(1)}-{m.group(2)}"
    m = CITATION.match(q) or CITATION_LAW_LAST.match(q)
    if not m:
        return None
    subs = "".join(f"-{s}" for s in re.findall(r"\((\w{1,4})\)", m.group("subs")))
    prefix = "s"
    if m.group("kind").lower().startswith("r"):
        prefix = "rule" if WHOLE_RULE.match(m.group("num")) and not subs else "r"
    law = (m.group("law") or "").strip(" ,").lower() or None
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


def _document(r: dict) -> dict:
    """A title match: decisions open their case page, everything else its law page (issue #12)."""
    kind = "case" if r["kind"] == "decision" else "law"
    return {"type": kind, "slug": r["slug"], "title": r["title"], "display": subtitle(r), "heading": None,
            "url": f"/{kind}s/{r['slug']}"}


def _case(cur: psycopg.Cursor, m: re.Match) -> dict | None:
    """The decision a neutral ("2024 ONCA 123") or SCR ("[1982] 1 SCR 175") citation names, at its paragraph."""
    citation = (f"{m['year']} {m['court'].upper()} {m['num']}" if m["year"]
                else f"[{m['ryear']}] {m['vol']} SCR {m['page']}")
    r = cur.execute("SELECT slug, title FROM documents WHERE neutral_citation = %s", (citation,)).fetchone()
    if not r:
        return None
    para = m["para"]
    return {"type": "case", "slug": r["slug"], "title": r["title"],
            "display": citation + (f" at para {para}" if para else ""), "heading": None,
            "url": f"/cases/{r['slug']}" + (f"#para-{para}" if para else "")}


def suggest(conn: psycopg.Connection, q: str, limit: int = SUGGEST_LIMIT) -> list[dict]:
    cur = conn.cursor(row_factory=dict_row)
    if m := CASE_CITATION.search(q):  # a case citation jumps to the decision (or paragraph)
        if case := _case(cur, m):
            return [case]
        q = f"{q[:m.start()]} {q[m.end():]}".strip(" ,") or q  # unknown: the style of cause may still match a title
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
        "SELECT slug, title, citation, kind, url FROM documents WHERE %s <%% lower(title)"
        " ORDER BY word_similarity(%s, lower(title)) DESC, title LIMIT 3", (q.lower(), q.lower()),
    ).fetchall()
    sections = cur.execute(
        "SELECT d.slug, d.title, s.pinpoint, s.heading FROM sections s JOIN documents d ON d.id = s.document_id"
        " LEFT JOIN sections p ON p.id = s.parent_id"  # subsection notes too, unless it is the section's own heading
        " WHERE s.kind IN ('section', 'subsection') AND s.heading IS DISTINCT FROM p.heading AND %s <%% s.heading"
        " ORDER BY word_similarity(%s, s.heading) DESC, d.title, s.sort_order LIMIT %s",
        (q, q, limit),
    ).fetchall()
    return ([_document(r) for r in laws] + [_section(r) for r in sections])[:limit]


def search_hits(conn: psycopg.Connection, q: str, query_vector: list[float], rerank=None) -> list:
    """The law top SEARCH_TOP_K (reordered by `rerank` when given), then the close web pages in their own lane.
    Plain-word search needs the rerank: fused order put Limitations Act s. 4 5th for "how long to sue" (#41);
    synonyms can't fix it (s. 4 never reaches the keyword top 50)."""
    return retrieve(conn, q, query_vector, top_k=SEARCH_TOP_K, rerank=rerank) + retrieve_web(conn, q, query_vector)


def group_by_law(hits: list) -> list[dict]:
    """Retrieved hits (in rank order) grouped by law, groups ordered by their best hit."""
    groups: dict[str, dict] = {}
    for h in hits:
        s = h.source
        g = groups.setdefault(s["slug"], {"slug": s["slug"], "title": s["title"], "kind": s["kind"],
                                          "subtitle": s.get("subtitle"), "hits": []})
        g["hits"].append({"pinpoint": s["pinpoint"], "display": s["display"], "citation": s["citation"],
                          "snippet": s["snippet"], "url": s["url"]})
    return list(groups.values())
