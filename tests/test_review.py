import inspect
import json
import re

import pytest
from fastapi.testclient import TestClient

from app.ask import AskResult, Retrieved, store_answer
from app.main import app, get_conn
from app.review import REFUSAL_STATUSES, RISK_LABELS, risk_reasons

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
    assert {"key": "dropped_claims", "label": "Claims dropped by quote check"} in item["risk"]


def test_queue_puts_guide_sections_after_risky_before_other_calm_drafts(client, conn):
    calm = make_answer(conn, question="calm")
    risky = make_answer(conn, status="unverified", question="risky")
    guide = make_answer(conn, question="guide")
    conn.execute("INSERT INTO guides (slug, title, intro, sort_order) VALUES ('mva', 'Motor vehicle accidents', 'i', 1)")
    conn.execute("INSERT INTO guide_sections (guide_slug, heading, question, answer_id, sort_order)"
                 " VALUES ('mva', 'Deadlines', 'guide', %s, 1)", (guide,))
    items = client.get("/review/queue", headers=REVIEWER).json()["data"]
    order = [i["id"] for i in items]
    assert order.index(risky) < order.index(guide) < order.index(calm)
    by_id = {i["id"]: i for i in items}
    assert by_id[guide]["guide"] == {"slug": "mva", "title": "Motor vehicle accidents", "heading": "Deadlines"}
    assert by_id[calm]["guide"] is None


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


@pytest.mark.parametrize("final, kept", [
    ("The draft quoted the wrong rule; removed.", False),  # #57: the edit removed the quote
    ("Two years.\n\n> a proceeding shall not\n> be commenced", True),  # kept, reflowed across quoted lines
    ("Two years: “a  proceeding shall not be commenced”.", True),  # kept inline, curly quotes and extra space
])
def test_edited_answer_shows_only_kept_claims(client, conn, final, kept):
    aid = make_answer(conn)
    client.post(f"/answers/{aid}/review", headers=REVIEWER, json={"decision": "edit", "final_markdown": final, "note": "n"})
    data = client.get(f"/answers/{aid}", headers=RESEARCHER).json()["data"]
    assert bool(data["claims"]) is kept
    reviewer = client.get(f"/answers/{aid}", headers=REVIEWER).json()["data"]
    assert reviewer["claims"] == data["claims"] and reviewer["draft_claims"][0]["quote"] == CLAIM["quote"]
    assert conn.execute("SELECT claims FROM answers WHERE id = %s", (aid,)).fetchone()[0][0]["quote"] == CLAIM["quote"]


@pytest.mark.parametrize("body", [{"decision": "reject"}, {"decision": "reject", "reason": "bad vibes"}])
def test_reject_requires_known_reason(client, conn, body):
    aid = make_answer(conn)
    assert client.post(f"/answers/{aid}/review", headers=REVIEWER, json=body).status_code == 422


@pytest.mark.parametrize("reason", ["unsupported_claim", "legal_advice"])
def test_reject_hides_draft_and_shows_reason(client, conn, reason):
    aid = make_answer(conn)
    r = client.post(f"/answers/{aid}/review", headers=REVIEWER, json={"decision": "reject", "reason": reason})
    assert r.status_code == 200
    data = client.get(f"/answers/{aid}", headers=RESEARCHER).json()["data"]
    assert data["status"] == "rejected" and data["review_reason"] == reason
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


def test_queue_links_trace_when_tracing_on(client, conn, monkeypatch):
    from app import tracing
    from test_tracing import FakeLangfuse

    monkeypatch.setattr(tracing, "_client", FakeLangfuse())
    monkeypatch.setattr(tracing, "_checked", True)
    result = AskResult("drafted", "d", [CLAIM], [])
    aid = store_answer(conn, "traced?", None, result, [HIT], {}, trace_id="t-1")
    item = next(i for i in client.get("/review/queue", headers=REVIEWER).json()["data"] if i["id"] == aid)
    assert item["trace_url"] == "https://lf.example/trace/t-1" and "trace_id" not in item


# --- 2.6 decisions logged ---

from app.review import edit_distance


def test_edit_distance():
    assert edit_distance("same text", "same text") == 0.0
    assert edit_distance("abc", "xyz") == 1.0
    assert 0 < edit_distance("Two years from discovery.", "Two years from the day of discovery.") < 0.5


@pytest.fixture
def scored(client, monkeypatch, tmp_path):
    from app import review, tracing
    from test_tracing import FakeLangfuse

    fake = FakeLangfuse()
    monkeypatch.setattr(tracing, "_client", fake)
    monkeypatch.setattr(tracing, "_checked", True)
    candidates = tmp_path / "gold_candidates.jsonl"
    monkeypatch.setattr(review, "CANDIDATES_PATH", candidates)
    return client, fake, candidates


def make_traced_answer(conn, trace_id="t-9"):
    result = AskResult("drafted", "Two years from discovery.", [CLAIM], [])
    return store_answer(conn, "How long to sue?", None, result, [HIT], {}, trace_id=trace_id)


def test_approve_posts_scores_and_no_candidate(scored, conn):
    client, fake, candidates = scored
    aid = make_traced_answer(conn)
    client.post(f"/answers/{aid}/review", headers=REVIEWER, json={"decision": "approve"})
    scores = {name: value for kind, name, value in fake.log if kind == "score"}
    assert scores["review_decision"] == "approved" and scores["edit_distance"] == 0.0
    assert scores["time_to_review_s"] >= 0 and "review_reason" not in scores
    assert not candidates.exists()


def test_edit_and_reject_become_gold_candidates_once(scored, conn):
    client, fake, candidates = scored
    edited = make_traced_answer(conn, "t-e")
    rejected = make_traced_answer(conn, "t-r")
    client.post(f"/answers/{edited}/review", headers=REVIEWER,
                json={"decision": "edit", "final_markdown": "Two years from the day of discovery.", "note": "precise"})
    client.post(f"/answers/{rejected}/review", headers=REVIEWER, json={"decision": "reject", "reason": "wrong_law"})
    from app.review import append_candidate
    append_candidate(conn, rejected)  # second append for the same answer is a no-op
    lines = [json.loads(l) for l in candidates.read_text().splitlines()]
    assert [(l["answer_id"], l["decision"]) for l in lines] == [(edited, "edited"), (rejected, "rejected")]
    assert lines[0]["final_markdown"] == "Two years from the day of discovery." and lines[1]["review_reason"] == "wrong_law"
    reasons = [value for kind, name, value in fake.log if kind == "score" and name == "review_reason"]
    assert reasons == ["wrong_law"]


def test_secondary_statute_is_stored_and_flagged_first(client, conn):
    result = AskResult("drafted", "Label.\n\nUnder the Municipal Act, 2001 ...", [CLAIM], [],
                       secondary_statute=["Municipal Act, 2001"])
    answer_id = store_answer(conn, "Municipal notice?", None, result, [HIT], {})
    flags = conn.execute("SELECT flags FROM answers WHERE id = %s", (answer_id,)).fetchone()[0]
    assert flags["secondary_statute"] == ["Municipal Act, 2001"]
    assert risk_reasons(flags)[0] == "secondary_statute"
    [item] = [i for i in client.get("/review/queue", headers=REVIEWER).json()["data"] if i["id"] == answer_id]
    assert "secondary_statute" in [r["key"] for r in item["risk"]]
    assert "secondary_statute" not in risk_reasons({"status": "drafted", "secondary_statute": []})


def test_advice_seeking_is_stored_and_flagged_after_secondary_statute(client, conn):
    """#7: a drafted answer to "do I have a case?" is risky even when the draft itself gives no advice."""
    calm = make_answer(conn, question="How long to sue?")
    result = AskResult("drafted", "Two years.", [CLAIM], [], advice_seeking=True)
    answer_id = store_answer(conn, "I slipped last week. Do I have a case?", None, result, [HIT], {})
    flags = conn.execute("SELECT flags FROM answers WHERE id = %s", (answer_id,)).fetchone()[0]
    assert flags["advice_seeking"] is True and risk_reasons(flags) == ["advice_seeking"]
    assert risk_reasons({**flags, "secondary_statute": ["X Act"], "retried": True}) == [
        "secondary_statute", "advice_seeking", "retried"]
    items = client.get("/review/queue", headers=REVIEWER).json()["data"]
    order = [i["id"] for i in items]
    assert order.index(answer_id) < order.index(calm)
    assert next(i for i in items if i["id"] == answer_id)["risk"] == [
        {"key": "advice_seeking", "label": "Asks for advice on their own facts"}]
    assert risk_reasons({"status": "drafted", "advice_seeking": False}) == []


def test_queue_marks_web_sources_addable_only_on_allowed_domains(client, conn):
    answer_id = make_answer(conn)
    sources = [{"url": "https://www.ontario.ca/page/x", "title": "X", "domain": "ontario.ca"},
               {"url": "https://www.somelawfirm.com/y", "title": "Y", "domain": "somelawfirm.com"}]
    conn.execute("UPDATE answers SET flags = flags || %s::jsonb WHERE id = %s",
                 (json.dumps({"web_fallback": True, "web_sources": sources}), answer_id))
    [item] = [i for i in client.get("/review/queue", headers=REVIEWER).json()["data"] if i["id"] == answer_id]
    assert [s["addable"] for s in item["web_sources"]] == [True, False]


def make_web_answer(conn, draft, sources):
    answer_id = make_answer(conn, status="web")
    conn.execute("UPDATE answers SET draft_markdown = %s, claims = '[]', flags = flags || %s::jsonb WHERE id = %s",
                 (draft, json.dumps({"web_fallback": True, "status": "web", "web_sources": sources}), answer_id))
    return answer_id


def test_released_web_answer_lists_http_sources_not_raw_markdown_links(client, conn):
    """#62: drafts stored before the fix end in a markdown link list; the view drops it and returns web_sources."""
    sources = [{"url": "https://www.ontario.ca/page/test", "title": "Test page", "domain": "ontario.ca"},
               {"url": "javascript:alert(1)", "title": "Evil", "domain": ""}]
    draft = ("**From the web, not our law library.** Check each source before relying on it.\n\nTwo years.\n\n"
             "**Web sources**\n\n- [Test page](https://www.ontario.ca/page/test) (ontario.ca)")
    answer_id = make_web_answer(conn, draft, sources)
    pending = client.get(f"/answers/{answer_id}", headers=RESEARCHER).json()["data"]
    assert "web_sources" not in pending  # unreviewed web links are not shown to researchers
    [item] = [i for i in client.get("/review/queue", headers=REVIEWER).json()["data"] if i["id"] == answer_id]
    assert "Web sources" not in item["draft_markdown"] and len(item["web_sources"]) == 1  # the edit form's start text
    assert client.post(f"/answers/{answer_id}/review", json={"decision": "approve"}, headers=REVIEWER).status_code == 200
    view = client.get(f"/answers/{answer_id}", headers=RESEARCHER).json()["data"]
    assert view["web_sources"] == [sources[0]]
    assert view["final_markdown"].endswith("Two years.") and "](" not in view["final_markdown"]


def test_edited_web_answer_keeps_its_sources(client, conn):
    answer_id = make_web_answer(conn, "**From the web, not our law library.**\n\nTwo years.",
                                [{"url": "https://www.ontario.ca/a", "title": "A", "domain": "ontario.ca"}])
    r = client.post(f"/answers/{answer_id}/review", headers=REVIEWER,
                    json={"decision": "edit", "final_markdown": "Two years, in most cases.", "note": "hedge"})
    assert r.status_code == 200
    view = client.get(f"/answers/{answer_id}", headers=RESEARCHER).json()["data"]
    assert view["edited"] and view["web_sources"][0]["url"] == "https://www.ontario.ca/a"


def test_recent_lists_only_released_answers_newest_reviewed_first(client, conn):
    """#10: the home page's recently reviewed answers — approved/edited only, never guide sections or draft text."""
    ids = {name: make_answer(conn, question=name) for name in ("old", "new", "edited", "rejected", "pending", "guide")}
    for name, decision in [("old", "approve"), ("new", "approve"), ("edited", "edit"), ("rejected", "reject"),
                           ("guide", "approve")]:
        body = {"decision": decision, "final_markdown": "Revised.", "note": "n", "reason": "out_of_scope"}
        assert client.post(f"/answers/{ids[name]}/review", json=body, headers=REVIEWER).status_code == 200
    for hours, name in [(3, "old"), (2, "edited"), (1, "new")]:  # decisions in one transaction share now()
        conn.execute("UPDATE answers SET reviewed_at = now() - make_interval(hours => %s) WHERE id = %s",
                     (hours, ids[name]))
    conn.execute("INSERT INTO guides (slug, title, intro, sort_order) VALUES ('mva', 'Motor vehicle accidents', 'i', 1)")
    conn.execute("INSERT INTO guide_sections (guide_slug, heading, question, answer_id, sort_order)"
                 " VALUES ('mva', 'Deadlines', 'guide', %s, 1)", (ids["guide"],))

    items = client.get("/answers?limit=5").json()["data"]
    assert [i["question"] for i in items] == ["new", "edited", "old"]
    assert set(items[0]) == {"id", "question", "reviewed_by", "reviewed_at"}
    assert items[0]["id"] == ids["new"] and items[0]["reviewed_by"] == "Demo Reviewer"
    assert [i["question"] for i in client.get("/answers?limit=1").json()["data"]] == ["new"]


@pytest.mark.parametrize("limit", ["0", "11", "x"])
def test_recent_limit_is_bounded(client, limit):
    assert client.get(f"/answers?limit={limit}").status_code == 422


def test_every_risk_key_has_a_label():
    """#65: the queue showed raw keys for flags without a label. Every key risk_reasons can emit needs one."""
    src = inspect.getsource(risk_reasons)
    literal = re.findall(r'reasons\.append\("(\w+)"\)', src)
    assert src.count("reasons.append(") == len(literal) + 1  # the one non-literal append is a refusal status
    assert set(literal) | set(REFUSAL_STATUSES) == set(RISK_LABELS)
    assert all(label.strip() for label in RISK_LABELS.values())
