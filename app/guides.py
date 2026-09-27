"""Topic guides: each section is an answer that went through review. A pending section shows only its retrieved
sources (like the Ask page), never the draft."""
import psycopg
from psycopg.rows import dict_row


def list_guides(conn: psycopg.Connection) -> list[dict]:
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT g.slug, g.title, g.intro, count(gs.id)::int AS sections,"
        " count(gs.id) FILTER (WHERE a.status IN ('approved', 'edited'))::int AS reviewed"
        " FROM guides g LEFT JOIN guide_sections gs ON gs.guide_slug = g.slug LEFT JOIN answers a ON a.id = gs.answer_id"
        " GROUP BY g.slug ORDER BY g.sort_order"
    ).fetchall()


def get_guide(conn: psycopg.Connection, slug: str) -> dict | None:
    cur = conn.cursor(row_factory=dict_row)
    guide = cur.execute("SELECT slug, title, intro FROM guides WHERE slug = %s", (slug,)).fetchone()
    if not guide:
        return None
    rows = cur.execute(
        "SELECT gs.heading, gs.question, gs.answer_id, a.status, a.final_markdown, a.claims, a.reviewed_at, a.flags,"
        " r.name AS reviewed_by FROM guide_sections gs LEFT JOIN answers a ON a.id = gs.answer_id"
        " LEFT JOIN users r ON r.id = a.reviewed_by WHERE gs.guide_slug = %s ORDER BY gs.sort_order", (slug,),
    ).fetchall()
    sections = []
    for r in rows:
        s = {"heading": r["heading"], "question": r["question"], "answer_id": r["answer_id"],
             "status": r["status"] or "not_drafted"}
        if r["status"] in ("approved", "edited"):
            s |= {"final_markdown": r["final_markdown"], "claims": r["claims"], "reviewed_by": r["reviewed_by"],
                  "reviewed_at": r["reviewed_at"], "edited": r["status"] == "edited"}
        elif r["status"] == "pending_review":
            s["sources"] = r["flags"].get("sources", [])
        sections.append(s)
    return {**guide, "sections": sections}
