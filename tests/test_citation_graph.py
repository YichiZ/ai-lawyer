from ingest.caselaw import parse_decision
from ingest.citations import build_citations
from ingest.statutes import load_document, parse_law
from test_statutes import LAW, row


def decision(citation):
    return parse_decision({"citation_en": citation, "name_en": f"Case {citation}", "document_date_en": "2023-01-01",
                           "url_en": "u", "unofficial_text_en": "Decision Content\n[1] Text.", "upstream_license": "l",
                           "dataset": "ONCA"})


def test_build_citations_links_sections_and_cases(conn):
    load_document(conn, parse_law(row(), LAW))
    load_document(conn, decision("2020 ONCA 1"))
    load_document(conn, decision("2023 ONCA 9"))
    citing = conn.execute("SELECT id FROM documents WHERE slug = '2023-onca-9'").fetchone()[0]
    refs = [("test-act", "s-15-2"), ("test-act", "s-4-9"), ("test-act", None)]
    cases = ["2020 ONCA 1", "2019 SCC 99", "2023 ONCA 9"]  # self-citation ignored
    assert build_citations(conn, citing, refs, cases) == 5
    rows = conn.execute(
        "SELECT c.kind, c.cited_citation, c.cited_slug, c.cited_pinpoint, d.slug, s.pinpoint FROM citations c"
        " LEFT JOIN documents d ON d.id = c.cited_document_id LEFT JOIN sections s ON s.id = c.cited_section_id"
        " WHERE c.citing_document_id = %s ORDER BY c.id", (citing,)).fetchall()
    assert rows == [
        ("statute", None, "test-act", "s-15-2", "test-act", "s-15-2"),
        ("statute", None, "test-act", "s-4-9", "test-act", "s-4"),       # unknown subsection falls back to the section
        ("statute", None, "test-act", None, "test-act", None),           # statute named without a section
        ("case", "2020 ONCA 1", None, None, "2020-onca-1", None),        # in the corpus
        ("case", "2019 SCC 99", None, None, None, None),                 # outside the corpus, kept as text
    ]
    assert build_citations(conn, citing, refs, cases) == 5  # rebuild replaces, no duplicates
    assert conn.execute("SELECT count(*) FROM citations WHERE citing_document_id = %s", (citing,)).fetchone()[0] == 5


def test_section_api_lists_citing_decisions(conn):
    from fastapi.testclient import TestClient

    from app.main import app, get_conn

    load_document(conn, parse_law(row(), LAW))
    load_document(conn, decision("2023 ONCA 9"))
    citing = conn.execute("SELECT id FROM documents WHERE slug = '2023-onca-9'").fetchone()[0]
    build_citations(conn, citing, [("test-act", "s-15-2")], [])  # cites a subsection of s. 15
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        data = TestClient(app).get("/laws/test-act/s-15").json()["data"]
    finally:
        app.dependency_overrides.clear()
    assert data["cited_by"]["total"] == 1
    assert data["cited_by"]["decisions"][0] == {"title": "Case 2023 ONCA 9", "citation": "2023 ONCA 9",
                                                "url": "/cases/2023-onca-9", "pinpoints": ["s. 15(2)"]}


def test_law_library_lists_laws_not_decisions(conn):
    from app.laws import list_laws

    load_document(conn, parse_law(row(), LAW))
    load_document(conn, decision("2023 ONCA 9"))
    kinds = {g["kind"] for g in list_laws(conn)}
    assert "decision" not in kinds and "statute" in kinds
