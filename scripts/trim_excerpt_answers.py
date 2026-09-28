"""Bring stored answers under the excerpt rule (#56): drafts written before verify_claims capped quotes from
excerpt-only documents (Toronto Municipal Code) may quote more than EXCERPT_CHARS of a section.

Pending answers: re-verify their claims with the cap, move dropped ones to flags.dropped_claims, recompose the draft
(or flag it failed when nothing is left), keep one snippet per excerpt-only section in flags.sources, and set
flags.excerpt_overflow when the answer's own sentences copy too much (the reviewer must edit those).
Approved/edited answers are only reported, never changed.

Run: uv run -m scripts.trim_excerpt_answers [--apply]   (default: dry run)
"""
import json
import os
import sys

import psycopg
from psycopg.rows import dict_row

from app.ask import (FAILED_DRAFT, WITHHELD, Retrieved, compose_draft, fit_excerpts, one_snippet_per_excerpt_section,
                     section_key, verify_claims, withheld)
from app.laws import excerpt_overflow

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
HEADING = "\n\n**What the law says**"


def _with_reproduction(sources: list[dict], excerpt_slugs: set[str]) -> list[dict]:
    return [{**s, "reproduction": "excerpt" if s.get("slug") in excerpt_slugs else "full"} for s in sources]


def _section_hits(conn: psycopg.Connection, sources: list[dict]) -> list[Retrieved]:
    """The excerpt-only sections among `sources`, as passages carrying the section's full text."""
    keys = {section_key(s): s for s in sources if s["reproduction"] == "excerpt"}
    return [Retrieved(s.get("chunk_id", ""), text, None, s) for (slug, pin), s in keys.items()
            for (text,) in conn.execute(  # a subsection pinpoint (older stored sources) reads its parent section
                "SELECT coalesce(p.text, s.text) FROM sections s JOIN documents d ON d.id = s.document_id"
                " LEFT JOIN sections p ON p.id = s.parent_id AND s.kind = 'subsection'"
                " WHERE d.slug = %s AND s.pinpoint = %s", (slug, pin))]


def _withhold_old_drops(dropped: list[dict], sources: list[dict]) -> list[dict]:
    """Earlier dropped claims (e.g. chunk_not_retrieved) from excerpt-only chunks still hold the model's quote."""
    excerpt_chunks = {s.get("chunk_id") for s in sources if s["reproduction"] == "excerpt"}
    return [withheld(d, d["reason"]) if d.get("chunk_id") in excerpt_chunks and not d.get("quote", "").endswith(WITHHELD)
            else d for d in dropped]


def trim(conn: psycopg.Connection, apply: bool) -> dict:
    """{"trimmed": [ids], "failed": [ids], "still_over": {id: [sections]}, "approved_over": {id: [sections]}}"""
    excerpt_slugs = {r[0] for r in conn.execute("SELECT slug FROM documents WHERE reproduction = 'excerpt'")}
    rows = conn.cursor(row_factory=dict_row).execute(
        "SELECT id, status, draft_markdown, final_markdown, claims, flags FROM answers ORDER BY id").fetchall()
    report = {"trimmed": [], "failed": [], "still_over": {}, "approved_over": {}}
    for a in rows:
        if a["status"] in ("approved", "edited"):
            if over := excerpt_overflow(conn, a["final_markdown"] or ""):
                report["approved_over"][a["id"]] = over
            continue
        if a["status"] != "pending_review" or not a["draft_markdown"]:
            continue
        claims = [{**c, "source": _with_reproduction([c["source"]], excerpt_slugs)[0]} for c in a["claims"] or []]
        chunks = {c["chunk_id"]: " ".join(x["quote"] for x in claims if x["chunk_id"] == c["chunk_id"]) for c in claims}
        kept, dropped = verify_claims(claims, chunks, {c["chunk_id"]: c["source"] for c in claims})
        old_sources = a["flags"].get("sources", [])
        new_sources = one_snippet_per_excerpt_section(_with_reproduction(old_sources, excerpt_slugs))
        prose = a["draft_markdown"].split(HEADING)[0]
        kept, cut, over = fit_excerpts(prose, kept, _section_hits(conn, new_sources + [c["source"] for c in kept]))
        dropped += cut
        if over:
            report["still_over"][a["id"]] = over
        old_drops = a["flags"].get("dropped_claims", [])
        new_drops = _withhold_old_drops(old_drops, new_sources + [c["source"] for c in claims])
        if not dropped and over == a["flags"].get("excerpt_overflow", []) and new_drops == old_drops and \
                [s["snippet"] for s in new_sources] == [s.get("snippet") for s in old_sources]:
            continue
        flags = {**a["flags"], "sources": new_sources, "excerpt_overflow": over, "dropped_claims": new_drops + dropped}
        if dropped and not kept:
            draft = FAILED_DRAFT
            flags |= {"status": "failed", "error": "every quote exceeded the excerpt cap for Toronto Municipal Code (#56)"}
            report["failed"].append(a["id"])
        else:
            draft = compose_draft(prose, kept) if dropped else a["draft_markdown"]
            report["trimmed"].append(a["id"])
        if apply:
            conn.execute("UPDATE answers SET draft_markdown = %s, claims = %s, flags = %s"
                         " WHERE id = %s AND status = 'pending_review'",
                         (draft, json.dumps(kept if dropped else a["claims"]), json.dumps(flags), a["id"]))
    return report


def main() -> int:
    apply = "--apply" in sys.argv[1:]
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        report = trim(conn, apply)
    for key, value in report.items():
        print(f"{key}: {value}")
    print("applied" if apply else "dry run (pass --apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
