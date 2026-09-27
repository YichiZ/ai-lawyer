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


def test_section_lines_carry_subsection_marginal_notes(client):
    lines = client.get("/laws/test-act/s-15").json()["data"]["lines"]
    assert [(l["level"], l["note"]) for l in lines] == [
        (1, "Ultimate limitation periods"), (1, "Same"), (2, None), (3, None), (1, None)]


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


# --- POST /ask ---

import re as _re

from contextlib import nullcontext

from app.main import get_ai, get_connect
from ingest.chunks import embed_pending, load_sections, plan_chunks, sync_chunks


class FakeAI:
    """Embeds everything to the same vector (distance 0) and quotes s. 4 from whichever chunk id holds it."""

    def __init__(self):
        self.prompts = []

    def embed_query(self, text):
        return [0.01] * 1536

    def generate(self, prompt, schema):
        self.prompts.append(prompt)
        cid = _re.search(r"\[(c\d+)\][^\n]*\n(Unless this Act)", prompt).group(1)
        return {"in_scope": True, "answer": "Generally two years from discovery.",
                "claims": [{"text": "Two years.", "chunk_id": cid, "quote": "a proceeding shall not be commenced after the second anniversary"}]}


@pytest.fixture
def ask_client(client, conn):
    doc_id = conn.execute("SELECT id FROM documents WHERE slug = 'test-act'").fetchone()[0]
    sync_chunks(conn, doc_id, plan_chunks("Test Act", load_sections(conn, doc_id)))
    embed_pending(conn, lambda t: [0.01] * 1536, model="fake", workers=1)
    fake = FakeAI()
    app.dependency_overrides[get_ai] = lambda: fake
    app.dependency_overrides[get_connect] = lambda: (lambda: nullcontext(conn))  # background draft sees test rows
    yield client, fake


def test_ask_returns_sources_and_pending_answer_without_draft(ask_client, conn):
    client, fake = ask_client
    r = client.post("/ask", json={"question": "How long do I have to sue after an injury?"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["status"] == "pending_review"
    assert "draft_markdown" not in data and "claims" not in data  # researcher never sees the draft before review
    assert 1 <= len(data["sources"]) <= 8
    assert {"slug", "pinpoint", "display", "citation", "snippet", "url"} <= set(data["sources"][0])
    status, claims, flags = conn.execute(
        "SELECT status, claims, flags FROM answers WHERE id = %s", (data["answer_id"],)).fetchone()
    assert status == "pending_review" and len(claims) == 1 and flags["status"] == "drafted"
    assert len(fake.prompts) == 1


@pytest.mark.parametrize("body", [{"question": "hi"}, {"question": "x" * 1001}, {}])
def test_ask_validates_question(ask_client, body):
    client, fake = ask_client
    r = client.post("/ask", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
    assert fake.prompts == []


def test_ask_is_traced_and_trace_id_stored(ask_client, conn, monkeypatch):
    from app import tracing
    from test_tracing import FakeLangfuse

    fake = FakeLangfuse()
    monkeypatch.setattr(tracing, "_client", fake)
    monkeypatch.setattr(tracing, "_checked", True)
    client, _ = ask_client
    data = client.post("/ask", json={"question": "How long do I have to sue after an injury?"}).json()["data"]
    started = [e[1] for e in fake.log if e[0] == "start"]
    assert started == ["ask", "embed_query", "retrieve", "store", "draft", "generate", "verify"]
    assert conn.execute("SELECT trace_id FROM answers WHERE id = %s", (data["answer_id"],)).fetchone()[0] == "trace-123"


def test_section_returns_plain_summary_when_present(client, conn):
    conn.execute("UPDATE sections SET plain_summary = 'You generally have two years.' WHERE pinpoint = 's-4'")
    data = client.get("/laws/test-act/s-4").json()["data"]
    assert data["plain_summary"] == "You generally have two years."
    assert client.get("/laws/test-act/s-15").json()["data"]["plain_summary"] is None



def test_ask_responds_before_drafting_and_draft_lands_in_background(ask_client, conn):
    client, fake = ask_client
    data = client.post("/ask", json={"question": "How long do I have to sue after an injury?"}).json()
    assert data["meta"]["timings_ms"]["sources"] >= 0 and "total" not in data["meta"]["timings_ms"]
    draft, flags = conn.execute("SELECT draft_markdown, flags FROM answers WHERE id = %s", (data["data"]["answer_id"],)).fetchone()
    assert draft.startswith("Generally two years") and flags["status"] == "drafted" and "draft" in flags["timings_ms"]


def test_failed_draft_is_flagged_for_the_reviewer(ask_client, conn):
    client, fake = ask_client

    def boom(prompt, schema):
        raise RuntimeError("504 DEADLINE_EXCEEDED")

    fake.generate = boom
    aid = client.post("/ask", json={"question": "How long do I have to sue after an injury?"}).json()["data"]["answer_id"]
    status, draft, flags = conn.execute("SELECT status, draft_markdown, flags FROM answers WHERE id = %s", (aid,)).fetchone()
    assert status == "pending_review" and flags["status"] == "failed" and "could not be drafted" in draft
    queue = client.get("/review/queue", headers={"X-Demo-User": "reviewer"}).json()["data"]
    assert "failed" in next(i for i in queue if i["id"] == aid)["risk"]


def test_answer_still_drafting_cannot_be_reviewed_and_is_not_queued(client, conn):
    from app.ask import create_pending

    aid = create_pending(conn, "Still drafting?", None, [], {"sources": 1}, None)
    assert all(i["id"] != aid for i in client.get("/review/queue", headers={"X-Demo-User": "reviewer"}).json()["data"])
    r = client.post(f"/answers/{aid}/review", headers={"X-Demo-User": "reviewer"}, json={"decision": "approve"})
    assert r.status_code == 409 and "drafting" in r.json()["error"]["message"]


def test_draft_lost_to_a_restart_is_flagged_failed_and_queued(client, conn):
    from app.ask import create_pending

    fresh = create_pending(conn, "Drafting now?", None, [], {"sources": 1}, None)
    lost = create_pending(conn, "Lost in a restart?", None, [], {"sources": 1}, None)
    conn.execute("UPDATE answers SET created_at = now() - interval '1 hour' WHERE id = %s", (lost,))
    queue = client.get("/review/queue", headers={"X-Demo-User": "reviewer"}).json()["data"]
    item = next(i for i in queue if i["id"] == lost)
    assert item["draft_status"] == "failed" and "failed" in item["risk"] and "could not be drafted" in item["draft_markdown"]
    assert all(i["id"] != fresh for i in queue)
    r = client.post(f"/answers/{lost}/review", headers={"X-Demo-User": "reviewer"},
                    json={"decision": "reject", "reason": "out_of_scope"})
    assert r.status_code == 200 and r.json()["data"]["status"] == "rejected"


def test_rerank_runs_in_background_and_updates_sources(ask_client, conn):
    client, fake = ask_client
    seen = {}

    def reverse(question, hits, top_k):
        seen["candidates"] = len(hits)
        return list(reversed(hits))[:top_k]

    fake.rerank = reverse
    body = client.post("/ask", json={"question": "How long do I have to sue after an injury?"}).json()["data"]
    shown = [s["chunk_id"] for s in body["sources"]]
    stored = [s["chunk_id"] for s in conn.execute("SELECT flags FROM answers WHERE id = %s", (body["answer_id"],)).fetchone()[0]["sources"]]
    assert seen["candidates"] >= len(shown)  # reranked the wider candidate list, after responding
    assert stored != shown and stored[0] == shown[-1] or len(shown) == 1


def test_web_fallback_creates_a_flagged_answer_for_review(ask_client, conn):
    client, fake = ask_client
    fake.search_web = lambda q: ("Ontario sets a two-year limit.", [{"url": "https://www.ontario.ca/a", "title": "Limits", "domain": "ontario.ca"}])
    r = client.post("/ask/web", json={"question": "How long do I have to sue in Ontario?"})
    assert r.status_code == 200 and r.json()["data"]["status"] == "pending_review"
    aid = r.json()["data"]["answer_id"]
    draft, flags = conn.execute("SELECT draft_markdown, flags FROM answers WHERE id = %s", (aid,)).fetchone()
    assert draft.startswith("**From the web, not our law library.**") and flags["web_fallback"] is True
    assert flags["status"] == "web" and flags["web_sources"][0]["domain"] == "ontario.ca"
    queue = client.get("/review/queue", headers={"X-Demo-User": "reviewer"}).json()["data"]
    assert "web_fallback" in next(i for i in queue if i["id"] == aid)["risk"]


def test_web_fallback_without_sources_is_not_found(ask_client, conn):
    client, fake = ask_client
    fake.search_web = lambda q: ("I could not find anything.", [])
    aid = client.post("/ask/web", json={"question": "Obscure question?"}).json()["data"]["answer_id"]
    flags = conn.execute("SELECT flags FROM answers WHERE id = %s", (aid,)).fetchone()[0]
    assert flags["status"] == "not_found" and flags["web_sources"] == []


def test_ask_reports_library_match(ask_client):
    client, _ = ask_client
    meta = client.post("/ask", json={"question": "How long do I have to sue after an injury?"}).json()["meta"]
    assert meta["library_match"] is True  # fake vectors are identical: distance 0


@pytest.fixture
def queue():
    import redis

    from app.jobs import Queue
    from app.main import get_queue
    q = Queue(redis.Redis(decode_responses=True), stream="test-ingest-api")
    q.ensure_group()
    app.dependency_overrides[get_queue] = lambda: q
    yield q
    q.redis.delete(q.stream)


REVIEWER = {"X-Demo-User": "reviewer"}


def test_ingest_reviewer_only_allowed_domains_and_status(client, queue):
    url = "https://www.ontario.ca/page/api-ingest-fixture"
    assert client.post("/ingest", json={"url": url, "in_scope": True}).status_code == 403
    refused = client.post("/ingest", json={"url": "https://www.canlii.org/en/on/x", "in_scope": True}, headers=REVIEWER)
    assert refused.status_code == 422 and "ontario.ca" in refused.json()["error"]["message"]
    r = client.post("/ingest", json={"url": url, "in_scope": True}, headers=REVIEWER)
    assert r.status_code == 202
    job = r.json()["data"]
    assert (job["status"], job["url"]) == ("queued", url)
    assert client.get(f"/ingest/{job['id']}").json()["data"]["status"] == "queued"
    assert client.get(f"/ingest/{'0' * 32}").status_code == 404


@pytest.mark.parametrize("extra", [{}, {"in_scope": False}])
def test_ingest_needs_the_reviewer_to_confirm_scope(client, queue, extra):
    r = client.post("/ingest", json={"url": "https://www.ontario.ca/page/unconfirmed", **extra}, headers=REVIEWER)
    assert r.status_code == 422 and "in_scope" in r.json()["error"]["message"]


def test_ingest_records_who_confirmed_scope(client, queue, conn):
    job = client.post("/ingest", json={"url": "https://www.ontario.ca/page/confirmed", "in_scope": True},
                      headers=REVIEWER).json()["data"]
    confirmed_by = conn.execute("SELECT u.role FROM ingest_jobs j JOIN users u ON u.id = j.scope_confirmed_by"
                                " WHERE j.id = %s", (job["id"],)).fetchone()
    assert confirmed_by == ("reviewer",)


@pytest.fixture
def web_page(client, conn):
    from ingest import web
    from test_web_ingest import PAGE

    parsed = web.parse_page("https://tc.canada.ca/en/drones/" + "long-path-" * 20, PAGE, "text/html")
    assert len(parsed.document["slug"]) == 120  # web slugs are capped at 120: the API must accept them
    load_document(conn, parsed)
    doc_id = conn.execute("SELECT id FROM documents WHERE slug = %s", (parsed.document["slug"],)).fetchone()[0]
    sync_chunks(conn, doc_id, plan_chunks("Drones", load_sections(conn, doc_id)))
    return parsed.document["slug"]


def test_web_page_shows_title_domain_and_fetched_date(client, web_page):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("America/Toronto")).date().isoformat()
    groups = {g["kind"]: g["documents"] for g in client.get("/laws").json()["data"]}
    [page] = groups["web"]
    assert (page["title"], page["subtitle"], page["section_count"]) == ("Slips and falls on city property",
                                                                        "tc.canada.ca", 2)
    assert page["date"] == today
    assert groups["statute"][0]["subtitle"] == "SO 2002, c 24, Sched B"  # other laws keep their citation
    doc = client.get(f"/laws/{web_page}").json()["data"]["document"]
    assert (doc["subtitle"], doc["date"]) == ("tc.canada.ca", today)


def test_delete_web_page_reviewer_only(client, web_page, conn):
    assert client.delete(f"/laws/{web_page}").status_code == 403
    assert client.delete("/laws/test-act", headers=REVIEWER).status_code == 409  # statutes are never removed here
    assert client.delete("/laws/no-such-page", headers=REVIEWER).status_code == 404
    r = client.delete(f"/laws/{web_page}", headers=REVIEWER)
    assert r.status_code == 200 and r.json()["data"] == {"slug": web_page, "deleted": True}
    assert conn.execute("SELECT count(*) FROM documents WHERE slug = %s", (web_page,)).fetchone() == (0,)
    assert conn.execute("SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.document_id"
                        " WHERE d.kind = 'web'").fetchone() == (0,)
    assert client.get("/laws/test-act").status_code == 200
