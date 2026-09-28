import json

from app.ask import FAILED_DRAFT, AskResult, compose_draft, store_answer
from app.review import decide
from ingest.bylaws import parse_chapter
from ingest.statutes import load_document
from scripts.trim_excerpt_answers import trim
from test_bylaws import RAW

LONG = " ".join(f"Rule {i}: every owner shall keep walkway {i} free from obstruction." for i in range(20))
SRC = {"slug": "toronto-municipal-code-743", "pinpoint": "743-10", "chunk_id": "c1", "snippet": LONG[:300] + "…",
       "citation": {"title": "", "reference": "City of Toronto Municipal Code, c 743, § 743-10"}}
STATUTE = {"slug": "test-act", "pinpoint": "s-4", "snippet": "x", "citation": {"title": "T", "reference": "s 4"}}


def _answer(conn, claims, status="pending_review"):
    result = AskResult("drafted", compose_draft("Owners must keep walkways clear.", claims), claims)
    aid = store_answer(conn, "Who clears walkways?", None, result, [], {})
    conn.execute("UPDATE answers SET flags = flags || %s::jsonb WHERE id = %s",
                 (json.dumps({"sources": [SRC, SRC, STATUTE]}), aid))
    if status != "pending_review":  # approved before the fix: reported only
        conn.execute("UPDATE answers SET status = %s, final_markdown = draft_markdown WHERE id = %s", (status, aid))
    return aid


def test_trim_caps_pending_answers_and_only_reports_approved_ones(conn):
    load_document(conn, parse_chapter(RAW, chapter="743", title="Streets", pdf_sha256="b" * 64,
                                      url="https://www.toronto.ca/x.pdf", license="© City of Toronto"))
    conn.execute("UPDATE sections SET text = %s WHERE pinpoint = '743-10'", (LONG,))
    long_claim = {"text": "t", "chunk_id": "c1", "quote": LONG[:500], "source": SRC}
    short_claim = {"text": "t", "chunk_id": "c2", "quote": "a proceeding shall not be commenced", "source": STATUTE}
    trimmed = _answer(conn, [long_claim, short_claim])
    failed = _answer(conn, [long_claim])
    approved = _answer(conn, [long_claim], status="approved")

    assert trim(conn, apply=False)["trimmed"] == [trimmed]  # dry run writes nothing
    assert LONG[:500] in conn.execute("SELECT draft_markdown FROM answers WHERE id = %s", (trimmed,)).fetchone()[0]

    report = trim(conn, apply=True)
    assert report == {"trimmed": [trimmed], "failed": [failed], "still_over": {}, "approved_over": {approved: ["§ 743-10"]}}
    draft, claims, flags = conn.execute("SELECT draft_markdown, claims, flags FROM answers WHERE id = %s", (trimmed,)).fetchone()
    assert LONG[:100] not in draft and "a proceeding shall not be commenced" in draft
    assert draft.startswith("Owners must keep walkways clear.") and len(claims) == 1
    assert flags["dropped_claims"][0]["reason"].startswith("excerpt-only source") and LONG[:100] not in json.dumps(flags["dropped_claims"])
    assert [s["snippet"] for s in flags["sources"]] == [SRC["snippet"], "", "x"]
    assert conn.execute("SELECT draft_markdown FROM answers WHERE id = %s", (failed,)).fetchone()[0] == FAILED_DRAFT
    assert LONG[:500] in conn.execute("SELECT final_markdown FROM answers WHERE id = %s", (approved,)).fetchone()[0]
    assert trim(conn, apply=True) == {"trimmed": [], "failed": [], "still_over": {}, "approved_over": {approved: ["§ 743-10"]}}


def test_trim_withholds_old_dropped_quotes_and_caps_split_section_claims(conn):
    load_document(conn, parse_chapter(RAW, chapter="743", title="Streets", pdf_sha256="b" * 64,
                                      url="https://www.toronto.ca/x.pdf", license="© City of Toronto"))
    conn.execute("UPDATE sections SET text = %s WHERE pinpoint = '743-10'", (LONG,))
    # two claims pinned to different "subsections" of one section: 250 + 200 characters together pass the cap
    a = {"text": "t", "chunk_id": "c1", "quote": LONG[:250], "source": {**SRC, "pinpoint": "743-10-a", "section": "743-10"}}
    b = {"text": "t", "chunk_id": "c2", "quote": LONG[400:600], "source": {**SRC, "pinpoint": "743-10-b", "section": "743-10"}}
    aid = _answer(conn, [a, b])
    old_drop = {"text": "t", "chunk_id": "c1", "quote": LONG[:900], "reason": "quote_not_in_chunk"}
    conn.execute("UPDATE answers SET flags = jsonb_set(flags, '{dropped_claims}', %s::jsonb) WHERE id = %s",
                 (json.dumps([old_drop]), aid))
    assert trim(conn, apply=True)["trimmed"] == [aid]
    claims, flags = conn.execute("SELECT claims, flags FROM answers WHERE id = %s", (aid,)).fetchone()
    assert [c["quote"] for c in claims] == [LONG[:250]]
    assert LONG[:100] not in json.dumps(flags["dropped_claims"]) and flags["dropped_claims"][0]["reason"] == "quote_not_in_chunk"
