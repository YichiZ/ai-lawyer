import pytest
from fastapi.testclient import TestClient

from app.ask import AskResult, Retrieved, store_answer
from app.main import app, get_conn

RESEARCHER = {"X-Demo-User": "researcher"}
REVIEWER = {"X-Demo-User": "reviewer"}
SOURCE = {"chunk_id": "c1", "slug": "test-act", "title": "Test Act", "pinpoint": "s-4", "display": "s. 4",
          "citation": {"title": "Test Act", "reference": "SO 2002, c 24, Sched B, s 4", "text": "Test Act, SO 2002, c 24, Sched B, s 4"},
          "snippet": "Unless this Act provides otherwise...", "url": "/laws/test-act/s-4"}
HIT = Retrieved("c1", "Unless this Act provides otherwise, a proceeding shall not be commenced.", 0.2, SOURCE, 0.03)
CLAIM = {"text": "Two years.", "chunk_id": "c1", "quote": "a proceeding shall not be commenced", "source": SOURCE}


def make_answer(conn, status="drafted", dropped=(), question="How long to sue?"):
    result = AskResult(status, "Two years.\n\n**What the law says**\n\n> a proceeding shall not be commenced",
                       [CLAIM] if status == "drafted" else [], list(dropped))
    return store_answer(conn, question, None, result, [HIT], {"sources": 300, "total": 2000})


@pytest.fixture
def client(conn):
    app.dependency_overrides[get_conn] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_seeded_demo_users(conn):
    rows = dict(conn.execute("SELECT role, name FROM users WHERE name LIKE 'Demo %'").fetchall())
    assert rows == {"researcher": "Demo Researcher", "reviewer": "Demo Reviewer"}


def test_queue_is_reviewer_only(client, conn):
    make_answer(conn)
    r = client.get("/review/queue", headers=RESEARCHER)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert client.get("/review/queue").status_code == 403  # no header = researcher


def test_unknown_demo_user_rejected(client):
    r = client.get("/review/queue", headers={"X-Demo-User": "admin"})
    assert r.status_code == 422


def test_queue_puts_risky_drafts_first(client, conn):
    calm = make_answer(conn, question="calm")
    risky = make_answer(conn, question="risky", dropped=[{**CLAIM, "quote": "made up", "reason": "quote_not_in_chunk"}])
    refused = make_answer(conn, status="unverified", question="refused")
    items = client.get("/review/queue", headers=REVIEWER).json()["data"]
    order = [i["id"] for i in items]
    assert order.index(risky) < order.index(calm) and order.index(refused) < order.index(calm)
    item = next(i for i in items if i["id"] == risky)
    assert item["draft_markdown"].startswith("Two years.")
    assert item["claims"][0]["source"]["display"] == "s. 4"
    assert item["dropped_claims"][0]["reason"] == "quote_not_in_chunk"
    assert "dropped_claims" in item["risk"]


def test_researcher_sees_no_draft_while_pending(client, conn):
    aid = make_answer(conn)
    data = client.get(f"/answers/{aid}", headers=RESEARCHER).json()["data"]
    assert data["status"] == "pending_review" and data["message"] == "Awaiting review"
    assert "draft_markdown" not in data and "final_markdown" not in data and "claims" not in data
    assert data["sources"][0]["display"] == "s. 4"


def test_approve_releases_draft(client, conn):
    aid = make_answer(conn)
    r = client.post(f"/answers/{aid}/review", headers=REVIEWER, json={"decision": "approve"})
    assert r.status_code == 200 and r.json()["data"]["status"] == "approved"
    data = client.get(f"/answers/{aid}", headers=RESEARCHER).json()["data"]
    assert data["final_markdown"].startswith("Two years.")
    assert data["reviewed_by"] == "Demo Reviewer" and data["reviewed_at"] and data["edited"] is False
    assert data["claims"][0]["quote"] == "a proceeding shall not be commenced"


def test_edit_requires_text_and_note_and_keeps_draft(client, conn):
    aid = make_answer(conn)
    r = client.post(f"/answers/{aid}/review", headers=REVIEWER, json={"decision": "edit", "final_markdown": "Better."})
    assert r.status_code == 422
    r = client.post(f"/answers/{aid}/review", headers=REVIEWER,
                    json={"decision": "edit", "final_markdown": "Better.", "note": "Tightened wording"})
    assert r.json()["data"]["status"] == "edited"
    draft, final, note = conn.execute("SELECT draft_markdown, final_markdown, review_note FROM answers WHERE id = %s", (aid,)).fetchone()
    assert draft.startswith("Two years.") and final == "Better." and note == "Tightened wording"
    assert client.get(f"/answers/{aid}", headers=RESEARCHER).json()["data"]["edited"] is True


@pytest.mark.parametrize("body", [{"decision": "reject"}, {"decision": "reject", "reason": "bad vibes"}])
def test_reject_requires_known_reason(client, conn, body):
    aid = make_answer(conn)
    assert client.post(f"/answers/{aid}/review", headers=REVIEWER, json=body).status_code == 422


def test_reject_hides_draft_and_shows_reason(client, conn):
    aid = make_answer(conn)
    client.post(f"/answers/{aid}/review", headers=REVIEWER, json={"decision": "reject", "reason": "unsupported_claim"})
    data = client.get(f"/answers/{aid}", headers=RESEARCHER).json()["data"]
    assert data["status"] == "rejected" and data["review_reason"] == "unsupported_claim"
    assert "final_markdown" not in data and "draft_markdown" not in data


def test_second_review_conflicts(client, conn):
    aid = make_answer(conn)
    client.post(f"/answers/{aid}/review", headers=REVIEWER, json={"decision": "approve"})
    r = client.post(f"/answers/{aid}/review", headers=REVIEWER, json={"decision": "approve"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"


def test_researcher_cannot_review(client, conn):
    aid = make_answer(conn)
    assert client.post(f"/answers/{aid}/review", headers=RESEARCHER, json={"decision": "approve"}).status_code == 403


def test_unknown_answer_404(client):
    assert client.get("/answers/999999", headers=RESEARCHER).status_code == 404
    assert client.post("/answers/999999/review", headers=REVIEWER, json={"decision": "approve"}).status_code == 404


def test_reviewer_sees_draft_while_pending(client, conn):
    aid = make_answer(conn)
    data = client.get(f"/answers/{aid}", headers=REVIEWER).json()["data"]
    assert data["draft_markdown"].startswith("Two years.")
