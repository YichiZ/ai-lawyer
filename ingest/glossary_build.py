"""Glossary definitions (Phase 4.3): one or two plain sentences per curated term, written by gemini-3.7-flash
from the term's source section only (its statutory definition when the laws define it)."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import psycopg

from ingest.statutes import display_pinpoint

TERMS_PATH = Path(__file__).resolve().parent.parent / "app" / "glossary_terms.tsv"
PROMPT = """Define the legal term "{term}" for a paralegal or law student, in 1-2 short sentences (grade 8 reading level).
Base the definition only on this text from {where}; if the text defines the term, follow that definition.
Do not add facts the text does not support. Not legal advice. Reply with the definition only.

<text>
{text}
</text>"""


def load_terms(path: Path = TERMS_PATH) -> list[tuple[str, str | None, str | None]]:
    out = []
    for line in path.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            parts = line.split("\t")
            out.append((parts[0].strip(), parts[1].strip(), parts[2].strip()) if len(parts) == 3 else (parts[0].strip(), None, None))
    return out


def resolve_source(conn: psycopg.Connection, term: str, slug: str | None, pinpoint: str | None):
    """(slug, pinpoint, text) of the given section, else of the section that defines “term”; None if neither."""
    if slug:
        row = conn.execute("SELECT d.slug, s.pinpoint, s.text FROM sections s JOIN documents d ON d.id = s.document_id"
                           " WHERE d.slug = %s AND s.pinpoint = %s", (slug, pinpoint)).fetchone()
        return tuple(row) if row else None
    for verb in ("means", "includes"):
        row = conn.execute(
            "SELECT d.slug, s.pinpoint, s.text FROM sections s JOIN documents d ON d.id = s.document_id"
            " WHERE s.text ILIKE %s ORDER BY (s.kind = 'subsection') DESC, d.slug, s.sort_order LIMIT 1",
            (f"%“{term}” {verb}%",)).fetchone()
        if row:
            return tuple(row)
    return None


def build_prompt(term: str, where: str, text: str) -> str:
    return PROMPT.format(term=term, where=where, text=text)


def upsert_definitions(conn: psycopg.Connection, terms, generate: Callable[[str], str], workers: int = 4) -> int:
    """Write definitions for terms not yet in glossary_terms. Returns model calls."""
    have = {r[0] for r in conn.execute("SELECT lower(term) FROM glossary_terms")}
    jobs = []
    for term, slug, pin in terms:
        if term.lower() in have:
            continue
        src = resolve_source(conn, term, slug, pin)
        if src is None:
            continue
        title = conn.execute("SELECT title FROM documents WHERE slug = %s", (src[0],)).fetchone()[0]
        jobs.append((term, src[0], src[1], build_prompt(term, f"{title}, {display_pinpoint(src[1])}", src[2])))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda j: " ".join(generate(j[3]).split()), jobs))
    with conn.transaction():
        for (term, slug, pin, _), definition in zip(jobs, results):
            conn.execute("INSERT INTO glossary_terms (term, plain_definition, source_slug, source_pinpoint)"
                         " VALUES (%s, %s, %s, %s) ON CONFLICT (term) DO NOTHING", (term, definition, slug, pin))
    return len(jobs)
