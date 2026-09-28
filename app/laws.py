"""Read queries for the law library. Every query is parameterized."""
import re

import psycopg
from psycopg.rows import dict_row

from app.format import indent_lines, mcgill_citation, subtitle
from app.glossary import find_terms
from ingest.statutes import display_pinpoint

EXCERPT_CHARS = 300  # documents with reproduction='excerpt' (City copyright) never return more than this
KIND_ORDER = ("statute", "regulation", "bylaw", "web", "decision")
DOC_FIELDS = ("slug, title, short_name, citation, kind, jurisdiction, in_force_from, date, url, source, "
              "upstream_license, reproduction")


SHINGLE_WORDS = 8  # a run of this many words copied verbatim counts as reproduced text


def excerpt(text: str) -> str:
    return text if len(text) <= EXCERPT_CHARS else text[:EXCERPT_CHARS].rstrip() + "…"


def _words(text: str) -> list[str]:
    """Lower-cased words, markdown blockquote markers and quote-mark variants ignored."""
    text = re.sub(r"(?m)^\s*>\s?", "", text).replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return text.lower().split()


def reproduced_chars(markdown: str, text: str, n: int = SHINGLE_WORDS) -> int:
    """How many characters of `markdown` copy `text`: words inside verbatim runs of at least `n` words of it. Counted
    on the markdown side, so a phrase the section repeats counts once per time it is shown. Catches quotes split
    across blockquotes or pasted into prose."""
    words, shown, copied = _words(text), _words(markdown), set()
    grams = {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}
    for i in range(len(shown) - n + 1):
        if tuple(shown[i:i + n]) in grams:
            copied.update(range(i, i + n))
    return sum(len(shown[i]) for i in copied) + max(len(copied) - 1, 0)  # words plus the spaces between them


def excerpt_overflow(conn: psycopg.Connection, markdown: str) -> list[str]:
    """Excerpt-only sections (e.g. "§ 743-41") of which `markdown` reproduces more than EXCERPT_CHARS characters."""
    rows = conn.execute(
        "SELECT s.pinpoint, s.text FROM sections s JOIN documents d ON d.id = s.document_id"
        " WHERE d.reproduction = 'excerpt' AND length(s.text) > %s", (EXCERPT_CHARS,)).fetchall()
    return [display_pinpoint(pin) for pin, text in rows if reproduced_chars(markdown, text) > EXCERPT_CHARS]


def list_laws(conn: psycopg.Connection) -> list[dict]:
    rows = conn.cursor(row_factory=dict_row).execute(
        "SELECT d.kind, d.slug, d.title, d.short_name, d.citation, d.in_force_from, d.date, d.url, d.reproduction,"
        " count(s.id) FILTER (WHERE s.kind = 'section') AS section_count"
        " FROM documents d LEFT JOIN sections s ON s.document_id = d.id WHERE d.kind <> 'decision'"
        " GROUP BY d.id ORDER BY d.title"
    ).fetchall()
    groups = {k: [] for k in KIND_ORDER}
    for r in rows:
        groups.setdefault(r["kind"], []).append({**r, "subtitle": subtitle(r)})
    return [{"kind": k, "documents": docs} for k, docs in groups.items() if docs]


def get_document(conn: psycopg.Connection, slug: str) -> dict | None:
    doc = conn.cursor(row_factory=dict_row).execute(
        f"SELECT id, {DOC_FIELDS} FROM documents WHERE slug = %s AND kind <> 'decision'", (slug,)
    ).fetchone()
    return {**doc, "subtitle": subtitle(doc)} if doc else None


def delete_web_page(conn: psycopg.Connection, slug: str) -> str | None:
    """Delete the web page `slug` (sections and chunks cascade) and its ingest job, so it can be added again later.
    Returns the document's kind (only 'web' is deleted), or None if there is no such document."""
    with conn.transaction():
        row = conn.execute("SELECT kind FROM documents WHERE slug = %s", (slug,)).fetchone()
        if row and row[0] == "web":
            conn.execute("DELETE FROM documents WHERE slug = %s AND kind = 'web'", (slug,))
            conn.execute("DELETE FROM ingest_jobs WHERE document_slug = %s", (slug,))
    return row[0] if row else None


def law_tree(conn: psycopg.Connection, document_id: int) -> list[dict]:
    rows = conn.cursor(row_factory=dict_row).execute(
        "SELECT s.pinpoint, s.kind, s.heading, p.pinpoint AS parent FROM sections s"
        " LEFT JOIN sections p ON p.id = s.parent_id"
        " WHERE s.document_id = %s AND s.kind IN ('part', 'section') ORDER BY s.sort_order",
        (document_id,),
    ).fetchall()
    return [{**r, "display": display_pinpoint(r["pinpoint"])} for r in rows]


def get_section(conn: psycopg.Connection, doc: dict, pinpoint: str) -> dict | None:
    cur = conn.cursor(row_factory=dict_row)
    s = cur.execute(
        "SELECT id, pinpoint, kind, heading, text, sort_order, plain_summary FROM sections"
        " WHERE document_id = %s AND pinpoint = %s",
        (doc["id"], pinpoint),
    ).fetchone()
    if not s:
        return None
    breadcrumb = cur.execute(
        "WITH RECURSIVE up AS ("
        "  SELECT parent_id, 0 AS depth FROM sections WHERE id = %s"
        "  UNION ALL SELECT s.parent_id, up.depth + 1 FROM sections s JOIN up ON s.id = up.parent_id)"
        " SELECT s.pinpoint, s.kind, s.heading FROM up JOIN sections s ON s.id = up.parent_id ORDER BY up.depth DESC",
        (s["id"],),
    ).fetchall()
    children = cur.execute(
        "SELECT pinpoint, kind, heading, text FROM sections WHERE parent_id = %s ORDER BY sort_order", (s["id"],)
    ).fetchall()
    sibling = "SELECT pinpoint FROM sections WHERE document_id = %s AND kind = %s AND sort_order {} %s ORDER BY sort_order {} LIMIT 1"
    prev = cur.execute(sibling.format("<", "DESC"), (doc["id"], s["kind"], s["sort_order"])).fetchone()
    nxt = cur.execute(sibling.format(">", "ASC"), (doc["id"], s["kind"], s["sort_order"])).fetchone()

    full = doc["reproduction"] == "full"
    shown = (lambda t: t) if full else excerpt
    # each subsection's marginal note goes on the line that opens it (labels are unique, so first lines are too)
    notes = {c["text"].split("\n")[0]: c["heading"] for c in children if c["kind"] == "subsection" and c["heading"]}
    document = {k: v for k, v in doc.items() if k != "id"}
    return {
        "pinpoint": s["pinpoint"],
        "display": display_pinpoint(s["pinpoint"]),
        "kind": s["kind"],
        "heading": s["heading"],
        "text": shown(s["text"]),
        "lines": [{**line, "note": notes.get(line["text"])} for line in indent_lines(shown(s["text"]))],
        "full_text": full,
        "plain_summary": s["plain_summary"],  # our own words, so shown even for excerpt-only by-laws
        "glossary": glossary_for(conn, shown(s["text"])),
        "cited_by": cited_by(conn, s["id"]),
        "citation": mcgill_citation(doc, s["pinpoint"]),
        "breadcrumb": [{**b, "display": display_pinpoint(b["pinpoint"])} for b in breadcrumb],
        "children": [{**c, "display": display_pinpoint(c["pinpoint"]), "text": shown(c["text"])} for c in children],
        "prev": prev["pinpoint"] if prev else None,
        "next": nxt["pinpoint"] if nxt else None,
        "document": document,
    }


def glossary(conn: psycopg.Connection) -> list[dict]:
    rows = conn.cursor(row_factory=dict_row).execute(
        "SELECT term, plain_definition, source_slug, source_pinpoint FROM glossary_terms ORDER BY lower(term)"
    ).fetchall()
    return [{"term": r["term"], "definition": r["plain_definition"],
             "source": {"url": f"/laws/{r['source_slug']}/{r['source_pinpoint']}",
                        "display": display_pinpoint(r["source_pinpoint"])} if r["source_slug"] else None}
            for r in rows]


def glossary_for(conn: psycopg.Connection, text: str) -> list[dict]:
    """Glossary entries whose term appears in `text` (whole words), in order of first appearance."""
    entries = {g["term"].lower(): g for g in glossary(conn)}
    return [entries[term.lower()] for _, _, term in find_terms(text, list(entries))]


def cited_by(conn: psycopg.Connection, section_id: int, limit: int = 20) -> dict:
    """Decisions citing this section or any of its subsections (newest first)."""
    rows = conn.cursor(row_factory=dict_row).execute(
        "SELECT d.title, d.neutral_citation, d.slug, d.date, array_agg(DISTINCT s.pinpoint) AS pins"
        " FROM citations c JOIN sections s ON s.id = c.cited_section_id JOIN documents d ON d.id = c.citing_document_id"
        " WHERE s.id = %s OR s.parent_id = %s GROUP BY d.id ORDER BY d.date DESC NULLS LAST", (section_id, section_id),
    ).fetchall()
    return {"total": len(rows), "decisions": [
        {"title": r["title"], "citation": r["neutral_citation"], "url": f"/cases/{r['slug']}",
         "pinpoints": [display_pinpoint(p) for p in sorted(r["pins"])]} for r in rows[:limit]]}
