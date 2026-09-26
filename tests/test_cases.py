from fastapi.testclient import TestClient

from app.main import app, get_conn
from ingest.caselaw import parse_decision
from ingest.citations import build_citations
from ingest.statutes import load_document, parse_law
from test_statutes import LAW, row


def decision(citation, name, text="Decision Content\n[1] First para. [2] Second para."):
    return parse_decision({"citation_en": citation, "name_en": name, "document_date_en": "2023-05-01", "url_en": "https://c/x",
                           "unofficial_text_en": text, "upstream_license": "non-commercial", "dataset": "ONCA"})


def test_case_page(conn):
    load_document(conn, parse_law(row(), LAW))
    load_document(conn, decision("2020 ONCA 1", "Old v. Case"))
    load_document(conn, decision("2023 ONCA 9", "Smith v. Jones"))
    load_document(conn, decision("2024 ONCA 5", "Later v. Case"))
    ids = dict(conn.execute("SELECT neutral_citation, id FROM documents WHERE kind = 'decision'").fetchall())
    build_citations(conn, ids["2023 ONCA 9"], [("test-act", "s-4")], ["2020 ONCA 1", "2015 SCC 3"])
    build_citations(conn, ids["2024 ONCA 5"], [], ["2023 ONCA 9"])
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        client = TestClient(app)
        data = client.get("/cases/2023-onca-9").json()["data"]
        assert client.get("/cases/nope").status_code == 404
    finally:
        app.dependency_overrides.clear()
    assert data["title"] == "Smith v. Jones" and data["court"] == "ONCA" and data["date"] == "2023-05-01"
    assert data["citation"] == {"title": "Smith v. Jones", "reference": "2023 ONCA 9", "text": "Smith v. Jones, 2023 ONCA 9"}
    assert [p["display"] for p in data["paragraphs"]] == ["para 1", "para 2"]
    assert data["cites"]["statutes"] == [{"label": "Test Act, s. 4", "url": "/laws/test-act/s-4"}]
    assert data["cites"]["cases"] == [{"citation": "2020 ONCA 1", "title": "Old v. Case", "url": "/cases/2020-onca-1"},
                                      {"citation": "2015 SCC 3", "title": None, "url": None}]
    assert data["cited_by"] == [{"citation": "2024 ONCA 5", "title": "Later v. Case", "url": "/cases/2024-onca-5"}]
    assert data["upstream_license"] == "non-commercial" and data["url"] == "https://c/x"


def test_suggest_jumps_to_case_and_paragraph(conn):
    load_document(conn, decision("2023 ONCA 9", "Smith v. Jones"))
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        client = TestClient(app)
        case = client.get("/suggest", params={"q": "2023 ONCA 9"}).json()["data"]
        para = client.get("/suggest", params={"q": "2023 onca 9 at para 2"}).json()["data"]
        missing = client.get("/suggest", params={"q": "1999 SCC 1"}).json()["data"]
    finally:
        app.dependency_overrides.clear()
    assert case == [{"type": "case", "slug": "2023-onca-9", "title": "Smith v. Jones", "display": "2023 ONCA 9",
                     "heading": None, "url": "/cases/2023-onca-9"}]
    assert para[0]["url"] == "/cases/2023-onca-9#para-2" and para[0]["display"] == "2023 ONCA 9 at para 2"
    assert missing == []


def test_claims_in_decisions_are_pinned_to_the_quoted_paragraph(conn):
    from app.ask import pinpoint_claims
    from ingest.chunks import plan_decision_chunks, sync_chunks

    load_document(conn, decision("2023 ONCA 9", "Smith v. Jones",
                                 "Decision Content\n[1] The facts were simple. [2] The appeal is dismissed with costs."))
    doc = conn.execute("SELECT id FROM documents WHERE slug = '2023-onca-9'").fetchone()[0]
    rows = conn.execute("SELECT id, pinpoint, kind, heading, text, NULL FROM sections WHERE document_id = %s ORDER BY sort_order", (doc,)).fetchall()
    sync_chunks(conn, doc, plan_decision_chunks("Smith v. Jones", "2023 ONCA 9",
                                                [dict(zip(("id", "pinpoint", "kind", "heading", "text", "parent"), r)) for r in rows]))
    cid = conn.execute("SELECT id FROM chunks WHERE document_id = %s", (doc,)).fetchone()[0]
    source = {"chunk_id": f"c{cid}", "slug": "2023-onca-9", "pinpoint": "para-1", "display": "para 1", "url": "/cases/2023-onca-9",
              "citation": {"title": "Smith v. Jones", "reference": "2023 ONCA 9 at para 1", "text": "x"}}
    [c] = pinpoint_claims(conn, [{"text": "Dismissed.", "chunk_id": f"c{cid}", "quote": "The appeal is dismissed", "source": source}])
    assert c["source"]["pinpoint"] == "para-2" and c["source"]["citation"]["reference"] == "2023 ONCA 9 at para 2"
    assert c["source"]["url"] == "/cases/2023-onca-9#para-2"


def test_decisions_are_cases_not_laws(conn):
    """Issue #12: a case name in the typeahead links to /cases/, and /laws/ never serves a decision."""
    load_document(conn, parse_law(row(), LAW))
    load_document(conn, decision("2016 ONCA 585", "Galota v. Festival Hall Developments Ltd."))
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        client = TestClient(app)
        items = client.get("/suggest", params={"q": "galota v festival hall"}).json()["data"]
        law = client.get("/laws/2016-onca-585")
        section = client.get("/laws/2016-onca-585/para-1")
        assert client.get("/laws/test-act").status_code == 200
    finally:
        app.dependency_overrides.clear()
    assert items[0] == {"type": "case", "slug": "2016-onca-585", "title": "Galota v. Festival Hall Developments Ltd.",
                        "display": "2016 ONCA 585", "heading": None, "url": "/cases/2016-onca-585"}
    assert not any(i["url"].startswith("/laws/2016-onca-585") for i in items)
    assert law.status_code == 404 and section.status_code == 404
