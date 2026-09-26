from pathlib import Path

from evals.ci_fixture import FIXTURE_DIR, load_fixture

CSV = ["documents.csv", "sections.csv", "chunks.csv"]


def test_fixture_files_exist():
    for name in CSV:
        assert (FIXTURE_DIR / name).exists(), f"run `make ci-fixture` to generate {name}"


def test_load_fixture_into_empty_db(conn):
    conn.execute("DELETE FROM documents")
    counts = load_fixture(conn, FIXTURE_DIR)
    assert counts["documents"] == 3 and counts["sections"] > 100 and counts["chunks"] > 30
    slugs = {r[0] for r in conn.execute("SELECT slug FROM documents")}
    assert slugs == {"limitations-act-2002", "dog-owners-liability-act", "toronto-municipal-code-743"}
    text, parent = conn.execute(
        "SELECT s.text, p.pinpoint FROM sections s JOIN documents d ON d.id = s.document_id"
        " LEFT JOIN sections p ON p.id = s.parent_id WHERE d.slug = 'limitations-act-2002' AND s.pinpoint = 's-15-2'"
    ).fetchone()
    assert "15th anniversary" in text and parent == "s-15"
    missing = conn.execute("SELECT count(*) FROM chunks WHERE embedding IS NULL").fetchone()[0]
    assert missing == 0
    # identity sequences moved past the loaded ids, so new rows don't collide
    conn.execute("INSERT INTO documents (sha256, kind, slug, title, source) VALUES ('z', 'statute', 'new-act', 'New', 't')")
