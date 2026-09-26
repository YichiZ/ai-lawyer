import psycopg
import pytest
from pgvector import HalfVector
from pgvector.psycopg import register_vector

from conftest import apply_schema

TABLES = {"documents", "sections", "chunks", "users", "answers"}
INDEXES = {
    "chunks_embedding_hnsw": "hnsw",
    "chunks_tsv_gin": "gin",
    "documents_title_trgm": "gin",
    "sections_heading_trgm": "gin",
    "sections_document_order": "btree",
    "documents_kind_court_date": "btree",
}


def insert_document(conn, sha="a" * 64, slug="limitations-act-2002"):
    return conn.execute(
        "INSERT INTO documents (sha256, kind, slug, title, source) VALUES (%s, 'statute', %s, 'Limitations Act, 2002', 'a2aj-laws') RETURNING id",
        (sha, slug),
    ).fetchone()[0]


def insert_section(conn, doc_id, pinpoint="s-4", text="A proceeding shall not be commenced..."):
    return conn.execute(
        "INSERT INTO sections (document_id, pinpoint, heading, text, sort_order) VALUES (%s, %s, 'Basic limitation period', %s, 1) RETURNING id",
        (doc_id, pinpoint, text),
    ).fetchone()[0]


def test_tables_exist(conn):
    rows = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()
    assert TABLES <= {r[0] for r in rows}


def test_extensions(conn):
    versions = dict(conn.execute("SELECT extname, extversion FROM pg_extension").fetchall())
    assert "pg_trgm" in versions
    major, minor = map(int, versions["vector"].split(".")[:2])
    assert (major, minor) >= (0, 8)


def test_indexes(conn):
    rows = conn.execute(
        "SELECT i.relname, am.amname FROM pg_class i JOIN pg_am am ON am.oid = i.relam WHERE i.relkind = 'i'"
    ).fetchall()
    found = dict(rows)
    for name, method in INDEXES.items():
        assert found.get(name) == method, f"{name}: expected {method}, got {found.get(name)}"


def test_schema_is_idempotent(test_db):
    with psycopg.connect(test_db, autocommit=True) as c:
        apply_schema(c)  # second application must not raise


def test_roundtrip_document_section_chunk(conn):
    register_vector(conn)
    doc = insert_document(conn)
    sec = insert_section(conn, doc)
    vec = HalfVector([0.1] * 1536)
    conn.execute(
        "INSERT INTO chunks (document_id, section_ids, pinpoint, text, text_sha256, embedding, embedding_model)"
        " VALUES (%s, %s, 's-4', 'limitation period text', %s, %s, 'gemini-embedding-2')",
        (doc, [sec], "b" * 64, vec),
    )
    text, dims, hit = conn.execute(
        "SELECT text, vector_dims(embedding::vector), tsv @@ websearch_to_tsquery('english', 'limitation periods')"
        " FROM chunks WHERE document_id = %s",
        (doc,),
    ).fetchone()
    assert (text, dims, hit) == ("limitation period text", 1536, True)


def test_tsv_follows_text(conn):
    doc = insert_document(conn)
    conn.execute("INSERT INTO chunks (document_id, pinpoint, text, text_sha256) VALUES (%s, 's-4', 'occupier duty', %s)", (doc, "c" * 64))
    conn.execute("UPDATE chunks SET text = 'dog owner liable' WHERE document_id = %s", (doc,))
    hit = conn.execute("SELECT tsv @@ to_tsquery('english', 'dog') FROM chunks WHERE document_id = %s", (doc,)).fetchone()[0]
    assert hit


def test_duplicate_sha256_rejected(conn):
    insert_document(conn)
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_document(conn, slug="other-slug")


def test_duplicate_pinpoint_rejected(conn):
    doc = insert_document(conn)
    insert_section(conn, doc)
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_section(conn, doc)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO users (name, role) VALUES ('X', 'admin')",
        "INSERT INTO answers (question, status) VALUES ('q?', 'published')",
        "INSERT INTO documents (sha256, kind, slug, title, source) VALUES ('d', 'blog', 's', 't', 'x')",
    ],
)
def test_check_constraints(conn, sql):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(sql)


def test_delete_document_cascades(conn):
    doc = insert_document(conn)
    insert_section(conn, doc)
    conn.execute("INSERT INTO chunks (document_id, pinpoint, text, text_sha256) VALUES (%s, 's-4', 't', %s)", (doc, "d" * 64))
    conn.execute("DELETE FROM documents WHERE id = %s", (doc,))
    counts = conn.execute(
        "SELECT (SELECT count(*) FROM sections WHERE document_id = %s), (SELECT count(*) FROM chunks WHERE document_id = %s)",
        (doc, doc),
    ).fetchone()
    assert counts == (0, 0)


def test_wrong_embedding_dimension_rejected(conn):
    register_vector(conn)
    doc = insert_document(conn)
    with pytest.raises(psycopg.errors.DataException):
        conn.execute(
            "INSERT INTO chunks (document_id, pinpoint, text, text_sha256, embedding) VALUES (%s, 's-4', 't', %s, %s)",
            (doc, "e" * 64, HalfVector([0.1] * 768)),
        )


def test_answer_defaults_to_pending_review(conn):
    uid = conn.execute("INSERT INTO users (name, role) VALUES ('R', 'researcher') RETURNING id").fetchone()[0]
    status, claims = conn.execute(
        "INSERT INTO answers (asked_by, question) VALUES (%s, 'How long to sue?') RETURNING status, claims", (uid,)
    ).fetchone()
    assert (status, claims) == ("pending_review", [])
