"""Case pages: one decision with its numbered paragraphs, what it cites and what cites it."""
import psycopg
from psycopg.rows import dict_row

from app.format import indent_lines
from ingest.statutes import display_pinpoint


def get_case(conn: psycopg.Connection, slug: str) -> dict | None:
    cur = conn.cursor(row_factory=dict_row)
    d = cur.execute(
        "SELECT id, slug, title, neutral_citation, court, date, url, upstream_license, plain_summary FROM documents"
        " WHERE slug = %s AND kind = 'decision'", (slug,),
    ).fetchone()
    if not d:
        return None
    sections = cur.execute("SELECT pinpoint, kind, text FROM sections WHERE document_id = %s ORDER BY sort_order",
                           (d["id"],)).fetchall()
    statutes = cur.execute(
        "SELECT DISTINCT cd.title, cd.slug, s.pinpoint, s.sort_order FROM citations c"
        " JOIN sections s ON s.id = c.cited_section_id JOIN documents cd ON cd.id = s.document_id"
        " WHERE c.citing_document_id = %s AND c.kind = 'statute' ORDER BY cd.title, s.sort_order", (d["id"],),
    ).fetchall()
    cases = cur.execute(
        "SELECT c.cited_citation, cd.title, cd.slug FROM citations c LEFT JOIN documents cd ON cd.id = c.cited_document_id"
        " WHERE c.citing_document_id = %s AND c.kind = 'case' ORDER BY c.id", (d["id"],),
    ).fetchall()
    cited_by = cur.execute(
        "SELECT DISTINCT d2.neutral_citation, d2.title, d2.slug, d2.date FROM citations c"
        " JOIN documents d2 ON d2.id = c.citing_document_id WHERE c.cited_document_id = %s AND c.kind = 'case'"
        " ORDER BY d2.date DESC", (d["id"],),
    ).fetchall()
    return {
        "slug": d["slug"], "title": d["title"], "court": d["court"], "date": d["date"], "url": d["url"],
        "upstream_license": d["upstream_license"], "plain_summary": d["plain_summary"],
        "citation": {"title": d["title"], "reference": d["neutral_citation"],
                     "text": f"{d['title']}, {d['neutral_citation']}"},
        "intro": next((s["text"] for s in sections if s["pinpoint"] == "intro"), None),
        "paragraphs": [{"pinpoint": s["pinpoint"], "display": display_pinpoint(s["pinpoint"]),
                        "lines": indent_lines(s["text"])} for s in sections if s["kind"] == "section"],
        "cites": {
            "statutes": [{"label": f"{r['title']}, {display_pinpoint(r['pinpoint'])}", "url": f"/laws/{r['slug']}/{r['pinpoint']}"}
                         for r in statutes],
            "cases": [{"citation": r["cited_citation"], "title": r["title"],
                       "url": f"/cases/{r['slug']}" if r["slug"] else None} for r in cases],
        },
        "cited_by": [{"citation": r["neutral_citation"], "title": r["title"], "url": f"/cases/{r['slug']}"} for r in cited_by],
    }
