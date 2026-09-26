"""A small committed corpus for CI (no downloads, no Vertex): exported from the dev DB, loaded with COPY.

Contents: the laws the Playwright specs use, with chunks + embeddings for the two statutes (the fake model
embeds a question as its best keyword match, so retrieval runs for real) and sections only for Toronto ch. 743.
"""
from pathlib import Path

import psycopg

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "corpus"
WITH_CHUNKS = ("limitations-act-2002", "dog-owners-liability-act")
SECTIONS_ONLY = ("toronto-municipal-code-743",)
TABLES = {
    "documents": ("id, sha256, kind, slug, title, short_name, citation, jurisdiction, in_force_from, url, source, "
                  "upstream_license, reproduction"),
    "sections": "id, document_id, parent_id, pinpoint, kind, heading, text, sort_order",
    "chunks": "id, document_id, section_ids, pinpoint, text, text_sha256, context, embedding, embedding_model",
}


def export_fixture(conn: psycopg.Connection, out: Path = FIXTURE_DIR) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    slugs = list(WITH_CHUNKS + SECTIONS_ONLY)
    where = {
        "documents": "slug = ANY(%(all)s)",
        "sections": "document_id IN (SELECT id FROM documents WHERE slug = ANY(%(all)s))",
        "chunks": "document_id IN (SELECT id FROM documents WHERE slug = ANY(%(chunked)s))",
    }
    counts = {}
    for table, cols in TABLES.items():
        query = psycopg.ClientCursor(conn).mogrify(f"SELECT {cols} FROM {table} WHERE {where[table]} ORDER BY id",
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
