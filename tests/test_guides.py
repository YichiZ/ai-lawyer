import pytest
from fastapi.testclient import TestClient

from app.ask import AskResult, Retrieved, store_answer
from app.main import app, get_conn

SOURCE = {"chunk_id": "c1", "slug": "test-act", "title": "Test Act", "pinpoint": "s-4", "display": "s. 4",
          "citation": {"title": "Test Act", "reference": "SO 2002, c 24, Sched B, s 4", "text": "Test Act, SO 2002, c 24, Sched B, s 4"},
          "snippet": "Unless...", "url": "/laws/test-act/s-4"}
CLAIM = {"text": "Two years.", "chunk_id": "c1", "quote": "a proceeding shall not be commenced", "source": SOURCE}


@pytest.fixture
def client(conn):
    hit = Retrieved("c1", "Unless this Act provides otherwise, a proceeding shall not be commenced.", 0.2, SOURCE)
    approved = store_answer(conn, "What is the deadline?", None, AskResult("drafted", "Two years.", [CLAIM], []), [hit], {})
    pending = store_answer(conn, "What must be shown?", None, AskResult("drafted", "Draft text.", [CLAIM], []), [hit], {})
    reviewer = conn.execute("SELECT id FROM users WHERE role = 'reviewer'").fetchone()[0]
    conn.execute("UPDATE answers SET status = 'approved', final_markdown = draft_markdown, reviewed_by = %s,"
                 " reviewed_at = now() WHERE id = %s", (reviewer, approved))
    conn.execute("INSERT INTO guides (slug, title, intro, sort_order) VALUES ('limitation-periods', 'Limitation periods',"
                 " 'How long you have.', 1)")
    conn.execute("INSERT INTO guide_sections (guide_slug, heading, question, answer_id, sort_order) VALUES"
                 " ('limitation-periods', 'Deadlines', 'What is the deadline?', %s, 1),"
                 " ('limitation-periods', 'What must be shown', 'What must be shown?', %s, 2)", (approved, pending))
    app.dependency_overrides[get_conn] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_guides(client):
    data = client.get("/guides").json()["data"]
    assert data == [{"slug": "limitation-periods", "title": "Limitation periods", "intro": "How long you have.",
                     "sections": 2, "reviewed": 1}]


def test_guide_shows_reviewed_sections_only(client):
    data = client.get("/guides/limitation-periods").json()["data"]
    first, second = data["sections"]
    assert first["heading"] == "Deadlines" and first["final_markdown"] == "Two years." and first["reviewed_by"] == "Demo Reviewer"
    assert first["claims"][0]["source"]["display"] == "s. 4"
    assert second["status"] == "pending_review" and "final_markdown" not in second and "draft_markdown" not in second


def test_unknown_guide_404(client):
    assert client.get("/guides/nope").status_code == 404
