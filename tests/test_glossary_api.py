import pytest
from fastapi.testclient import TestClient

from app.main import app, get_conn
from ingest.statutes import load_document, parse_law
from test_statutes import LAW, row


@pytest.fixture
def client(conn):
    load_document(conn, parse_law(row(), LAW))
    conn.execute("INSERT INTO glossary_terms (term, plain_definition, source_slug, source_pinpoint) VALUES"
                 " ('claim', 'A request for a remedy for an injury, loss or damage.', 'test-act', 's-1'),"
                 " ('occupier', 'The person in charge of a property.', NULL, NULL)")
    app.dependency_overrides[get_conn] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_glossary_lists_terms_alphabetically_with_sources(client):
    data = client.get("/glossary").json()["data"]
    assert [t["term"] for t in data] == ["claim", "occupier"]
    assert data[0]["source"] == {"url": "/laws/test-act/s-1", "display": "s. 1"} and data[1]["source"] is None


def test_section_lists_glossary_terms_found_in_its_text(client):
    data = client.get("/laws/test-act/s-1").json()["data"]
    assert [g["term"] for g in data["glossary"]] == ["claim"]
