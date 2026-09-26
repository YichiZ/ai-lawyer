import pytest
from fastapi.testclient import TestClient

from app.main import app, get_conn
from ingest.bylaws import parse_chapter
from ingest.statutes import load_document, parse_law
from test_bylaws import RAW as BYLAW_RAW
from test_statutes import LAW, SECTIONS, row


@pytest.fixture
def client(conn):
    load_document(conn, parse_law(row(), LAW))
    load_document(conn, parse_chapter(BYLAW_RAW, chapter="743", title="Streets and Sidewalks, Use of",
                                      pdf_sha256="b" * 64, url="https://www.toronto.ca/legdocs/municode/1184_743.pdf",
                                      license="© City of Toronto"))
    app.dependency_overrides[get_conn] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_laws_grouped_by_kind(client):
    body = client.get("/laws").json()
    assert body["error"] is None
    groups = {g["kind"]: g["documents"] for g in body["data"]}
    [statute] = groups["statute"]
    assert statute["slug"] == "test-act" and statute["citation"] == "SO 2002, c 24, Sched B"
    assert statute["section_count"] == 5  # sections only, not parts or subsections
    assert statute["in_force_from"] == "2024-12-04"
    assert groups["bylaw"][0]["reproduction"] == "excerpt"
    assert body["meta"]["total"] == 2


def test_law_tree_has_parts_and_sections_without_text(client):
    body = client.get("/laws/test-act").json()
    doc, tree = body["data"]["document"], body["data"]["tree"]
    assert doc["title"] == "Test Act" and doc["url"].startswith("https://www.ontario.ca/laws/")
    assert [n["pinpoint"] for n in tree][:3] == ["s-1", "part-i", "s-4"]
    assert {n["kind"] for n in tree} == {"part", "section"}
    assert all("text" not in n for n in tree)
    s4 = next(n for n in tree if n["pinpoint"] == "s-4")
    assert s4["display"] == "s. 4" and s4["parent"] == "part-i" and s4["heading"] == "Basic limitation period"


def test_section_full_text_with_navigation(client):
    body = client.get("/laws/test-act/s-15").json()["data"]
    assert body["text"] == SECTIONS["15"] and body["full_text"] is True
    assert body["display"] == "s. 15"
    assert [b["pinpoint"] for b in body["breadcrumb"]] == ["part-ii"]
    assert [c["pinpoint"] for c in body["children"]] == ["s-15-1", "s-15-2", "s-15-2.1"]
    assert body["prev"] == "s-4" and body["next"] == "ss-25-49"
    assert body["document"]["upstream_license"] == "See upstream license"


def test_subsection_breadcrumb(client):
    body = client.get("/laws/test-act/s-15-2").json()["data"]
    assert [b["pinpoint"] for b in body["breadcrumb"]] == ["part-ii", "s-15"]
    assert body["display"] == "s. 15(2)"


def test_part_lists_its_sections(client):
    body = client.get("/laws/test-act/part-ii").json()["data"]
    assert body["kind"] == "part"
    assert [c["pinpoint"] for c in body["children"]] == ["s-15", "ss-25-49", "schedule"]


def test_excerpt_only_document_never_returns_full_text(client):
    body = client.get("/laws/toronto-municipal-code-743/743-10").json()["data"]
    assert body["full_text"] is False
    assert body["document"]["reproduction"] == "excerpt"
    assert body["document"]["url"] == "https://www.toronto.ca/legdocs/municode/1184_743.pdf"
    assert len(body["text"]) <= 301  # EXCERPT_CHARS + ellipsis


def test_unknown_law_404_envelope(client):
    r = client.get("/laws/no-such-act")
    assert r.status_code == 404
    assert r.json() == {"data": None, "error": {"code": "not_found", "message": "No law 'no-such-act'"}, "meta": None}


def test_unknown_pinpoint_404(client):
    r = client.get("/laws/test-act/s-999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("path", ["/laws/Test_Act", "/laws/test-act/s 4", "/laws/test-act/s-4;drop"])
def test_invalid_characters_422(client, path):
    r = client.get(path)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request" and r.json()["data"] is None


def test_section_has_indented_lines_and_citation(client):
    body = client.get("/laws/test-act/s-15-2").json()["data"]
    assert [l["level"] for l in body["lines"]] == [1, 2, 3]
    assert body["citation"]["text"] == "Test Act, SO 2002, c 24, Sched B, s 15(2)"
