"""Chunk context (Phase 3.5): gemini-3.5-flash-lite writes 1-2 sentences placing each chunk in its law.

Input: the law's title, the outline of the chunk's Part (section headings, capped) and the chunk text. The sentences
go into the embedding input only; the chunk text (which quotes are verified against) is never changed. Writing a
chunk's sentences clears its embedding so `embed_pending` re-embeds it.
"""

from typing import Callable

import psycopg

from ingest.chunks import LAW_KINDS, run_batched
from ingest.statutes import display_pinpoint

MAX_OUTLINE_LINES = 60
PROMPT = """Here is the outline of part of {title}:
{outline}

Here is a passage from {title}, {display}:
<passage>
{text}
</passage>

In 1-2 plain sentences, say what this passage is about and where it sits in the law (who it applies to, what
situation it covers), to help search find it. Do not give legal advice. Reply with the sentences only."""


def part_outline(sections: list[dict], pinpoint: str) -> str:
    """Headings of the Part containing `pinpoint` (or of the whole law when it has no Parts), capped."""
    target = next((s for s in sections if s["pinpoint"] == pinpoint), None)
    part = target["parent"] if target else None
    lines = [s["heading"] for s in sections if s["pinpoint"] == part and s["heading"]]
    lines += [f"{display_pinpoint(s['pinpoint'])} {s['heading'] or ''}".strip() for s in sections
              if s["kind"] == "section" and s["parent"] == part]
    return "\n".join(lines[:MAX_OUTLINE_LINES + 1])


def build_prompt(title: str, display: str, outline: str, text: str) -> str:
    return PROMPT.format(title=title, display=display, outline=outline, text=text)


def contextualize_pending(conn: psycopg.Connection, generate: Callable[[str], str], workers: int = 8) -> int:
    """Write situating sentences for chunks that have none. Returns the number of model calls."""
    rows = conn.execute(
        "SELECT c.id, c.document_id, d.title, coalesce(s.pinpoint, c.pinpoint), c.text FROM chunks c"
        " JOIN documents d ON d.id = c.document_id LEFT JOIN sections s ON s.id = c.section_ids[1]"
        " WHERE c.situating IS NULL AND d.kind = ANY(%s) ORDER BY c.id", (LAW_KINDS,)
    ).fetchall()
    outlines: dict[tuple[int, str], str] = {}
    sections_by_doc: dict[int, list[dict]] = {}
    jobs = []
    for cid, doc_id, title, pin, text in rows:
        if doc_id not in sections_by_doc:
            sections_by_doc[doc_id] = [dict(zip(("pinpoint", "kind", "heading", "parent"), r)) for r in conn.execute(
                "SELECT s.pinpoint, s.kind, s.heading, p.pinpoint FROM sections s LEFT JOIN sections p ON p.id = s.parent_id"
                " WHERE s.document_id = %s ORDER BY s.sort_order", (doc_id,))]  # outline only: no text, the cache spans the run
        key = (doc_id, pin)
        if key not in outlines:
            outlines[key] = part_outline(sections_by_doc[doc_id], pin)
        jobs.append((cid, build_prompt(title, display_pinpoint(pin), outlines[key], text)))

    return run_batched(conn, generate, jobs, lambda cid, out: conn.execute(
        "UPDATE chunks SET situating = %s, embedding = NULL WHERE id = %s", (" ".join(out.split()), cid)), workers)
