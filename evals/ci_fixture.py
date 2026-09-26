"""A small committed corpus for CI (no downloads, no Vertex): exported from the dev DB, loaded with COPY.

Contents: the laws the Playwright specs use, with chunks + embeddings for the two statutes (the fake model
embeds a question as its best keyword match, so retrieval runs for real) and sections only for Toronto ch. 743
(cut to excerpts: City copyright).
"""
from pathlib import Path

import psycopg

from app.laws import EXCERPT_CHARS

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "corpus"
WITH_CHUNKS = ("limitations-act-2002", "dog-owners-liability-act", "2016-onca-585")  # + Galota (cites LA s. 4, 5(1))
SECTIONS_ONLY = ("toronto-municipal-code-743",)
TABLES = {
    "documents": ("id, sha256, kind, slug, title, short_name, citation, jurisdiction, in_force_from, url, source, "
                  "upstream_license, reproduction, neutral_citation, court, date, plain_summary"),
    "sections": "id, document_id, parent_id, pinpoint, kind, heading, text, sort_order, plain_summary",
    "chunks": "id, document_id, section_ids, pinpoint, text, text_sha256, context, embedding, embedding_model",
    "citations": ("id, citing_document_id, kind, cited_citation, cited_document_id, cited_slug, cited_pinpoint,"
                  " cited_section_id"),
}


def export_fixture(conn: psycopg.Connection, out: Path = FIXTURE_DIR) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    slugs = list(WITH_CHUNKS + SECTIONS_ONLY)
    where = {
        "documents": "slug = ANY(%(all)s)",
        "sections": "document_id IN (SELECT id FROM documents WHERE slug = ANY(%(all)s))",
        "chunks": "document_id IN (SELECT id FROM documents WHERE slug = ANY(%(chunked)s))",
        # only links whose both ends are in the fixture (others would break foreign keys)
        "citations": ("citing_document_id IN (SELECT id FROM documents WHERE slug = ANY(%(all)s))"
                      " AND (cited_section_id IS NULL OR cited_section_id IN (SELECT s.id FROM sections s JOIN documents d"
                      " ON d.id = s.document_id WHERE d.slug = ANY(%(all)s)))"
                      " AND (cited_document_id IS NULL OR cited_document_id IN (SELECT id FROM documents WHERE slug = ANY(%(all)s)))"),
    }
    # excerpt-only documents (City copyright) are cut to what the app may show, so the repo never holds full text
    select = {**TABLES, "sections": TABLES["sections"].replace(
        "text,", f"CASE WHEN document_id IN (SELECT id FROM documents WHERE reproduction = 'excerpt')"
                 f" THEN left(text, {EXCERPT_CHARS}) ELSE text END AS text,")}
    counts = {}
    for table in TABLES:
        query = psycopg.ClientCursor(conn).mogrify(f"SELECT {select[table]} FROM {table} WHERE {where[table]} ORDER BY id",
                                      {"all": slugs, "chunked": list(WITH_CHUNKS)})
        with (out / f"{table}.csv").open("wb") as f, conn.cursor().copy(f"COPY ({query}) TO STDOUT WITH CSV HEADER") as cp:
            for block in cp:
                f.write(block)
        counts[table] = conn.execute(f"SELECT count(*) FROM ({query}) t").fetchone()[0]
    return counts


def load_fixture(conn: psycopg.Connection, src: Path = FIXTURE_DIR) -> dict[str, int]:
    """Load into a database that has the schema and no documents. Keeps ids, then moves identity sequences on."""
    counts = {}
    with conn.transaction():
        for table, cols in TABLES.items():
            with (src / f"{table}.csv").open("rb") as f, \
                    conn.cursor().copy(f"COPY {table} ({cols}) FROM STDIN WITH CSV HEADER") as cp:
                while block := f.read(1 << 16):
                    cp.write(block)
            counts[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            conn.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT max(id) FROM {table}))")
    return counts
