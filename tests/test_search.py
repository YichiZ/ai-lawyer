import pytest

from app.search import is_question, parse_citation


@pytest.mark.parametrize(
    "q, law, pinpoint",
    [
        ("s. 4", None, "s-4"),
        ("s 4(1)", None, "s-4-1"),
        ("section 15(2)", None, "s-15-2"),
        ("ss. 4", None, "s-4"),
        ("r. 2.02", None, "r-2.02"),
        ("rule 14.08(1)", None, "r-14.08-1"),
        ("§ 743-9", None, "743-9"),
        ("743-44", None, "743-44"),
        ("Limitations Act s. 4", "limitations act", "s-4"),
        ("OLA s 6.1", "ola", "s-6.1"),
        ("negligence act, s. 3", "negligence act", "s-3"),
    ],
)
def test_parse_citation(q, law, pinpoint):
    assert parse_citation(q) == (law, pinpoint)


@pytest.mark.parametrize("q", ["slip and fall", "dog bite", "limitation period", "4 wheels", ""])
def test_not_a_citation(q):
    assert parse_citation(q) is None


@pytest.mark.parametrize(
    "q, yes",
    [("How long do I have to sue?", True), ("can I sue the city", True), ("what is an occupier", True),
     ("slip and fall", False), ("s. 4", False), ("occupiers liability", False)],
)
def test_is_question(q, yes):
    assert is_question(q) is yes


# --- endpoints ---

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app, get_ai, get_conn  # noqa: E402
from ingest.chunks import embed_pending, load_sections, plan_chunks, sync_chunks  # noqa: E402
from ingest.statutes import load_document, parse_law  # noqa: E402
from test_statutes import LAW, row  # noqa: E402


class FakeAI:
    def embed_query(self, text):
        return [0.01] * 1536


@pytest.fixture
def client(conn):
    load_document(conn, parse_law(row(), LAW))
    doc_id = conn.execute("SELECT id FROM documents WHERE slug = 'test-act'").fetchone()[0]
    sync_chunks(conn, doc_id, plan_chunks("Test Act", load_sections(conn, doc_id)))
    embed_pending(conn, lambda t: [0.01] * 1536, model="fake", workers=1)
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_ai] = lambda: FakeAI()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_suggest_citation_jumps_to_section(client):
    data = client.get("/suggest", params={"q": "Test Act s. 15(2)"}).json()["data"]
    assert data[0]["type"] == "section" and data[0]["url"] == "/laws/test-act/s-15-2"
    assert data[0]["display"] == "s. 15(2)"


def test_suggest_matches_headings_and_titles(client):
    data = client.get("/suggest", params={"q": "limitation perio"}).json()["data"]
    urls = [d["url"] for d in data]
    assert "/laws/test-act/s-4" in urls  # heading "Basic limitation period"
    laws = client.get("/suggest", params={"q": "test ac"}).json()["data"]
    assert laws[0] == {"type": "law", "slug": "test-act", "title": "Test Act", "display": "SO 2002, c 24, Sched B",
                       "heading": None, "url": "/laws/test-act"}


@pytest.mark.parametrize("q", ["", "a", "x" * 201])
def test_suggest_validates(client, q):
    assert client.get("/suggest", params={"q": q}).status_code == 422


def test_search_groups_by_law_and_offers_ask(client):
    body = client.get("/search", params={"q": "How long do I have to sue?"}).json()
    groups, meta = body["data"], body["meta"]
    assert groups[0]["slug"] == "test-act" and groups[0]["title"] == "Test Act"
    assert {"display", "snippet", "url"} <= set(groups[0]["hits"][0])
    assert meta["ask_this"] is True


def test_search_citation_query_is_not_a_question(client):
    assert client.get("/search", params={"q": "limitation period"}).json()["meta"]["ask_this"] is False
