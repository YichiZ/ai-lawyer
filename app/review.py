"""Human review: every drafted answer waits in pending_review until a reviewer approves, edits or rejects it."""
import difflib
import json
import os
import re
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from app import tracing
from app.laws import excerpt_only_slugs, withhold_excerpts
from ingest.web import site_of

REFUSAL_STATUSES = ("not_found", "out_of_scope", "unverified")
# Edited/rejected answers are gold-set candidates (promoted by hand, never automatically).
CANDIDATES_PATH = Path(os.environ.get("GOLD_CANDIDATES_PATH",
                                      Path(__file__).resolve().parent.parent / "evals" / "gold_candidates.jsonl"))


def risk_reasons(flags: dict) -> list[str]:
    reasons = []
    if flags.get("excerpt_overflow"):  # first: cannot be approved until the copied by-law text is shortened (#56)
        reasons.append("excerpt_overflow")
    if flags.get("secondary_statute"):  # first: the draft states a law we don't hold, from a decision quoting it
        reasons.append("secondary_statute")
    if flags.get("advice_seeking"):  # next: read the whole draft for advice before checking its details (#7)
        reasons.append("advice_seeking")
    if flags.get("status") in REFUSAL_STATUSES:
        reasons.append(flags["status"])
    if flags.get("dropped_claims"):
        reasons.append("dropped_claims")
    if flags.get("retried"):
        reasons.append("retried")
    if flags.get("status") == "failed":
        reasons.append("failed")
    if flags.get("web_fallback"):
        reasons.append("web_fallback")
    return reasons


def queue(conn: psycopg.Connection) -> list[dict]:
    rows = conn.cursor(row_factory=dict_row).execute(
        "SELECT a.id, a.question, a.draft_markdown, a.claims, a.flags, a.created_at, a.trace_id, u.name AS asked_by,"
        " (SELECT jsonb_build_object('slug', g.slug, 'title', g.title, 'heading', gs.heading) FROM guide_sections gs"
        "  JOIN guides g ON g.slug = gs.guide_slug WHERE gs.answer_id = a.id LIMIT 1) AS guide"
        " FROM answers a LEFT JOIN users u ON u.id = a.asked_by"
        " WHERE a.status = 'pending_review' AND a.draft_markdown IS NOT NULL"
        " ORDER BY a.created_at, a.id"
    ).fetchall()
    items = []
    for r in rows:
        flags, trace_id = r.pop("flags"), r.pop("trace_id")
        risk = risk_reasons(flags)
        items.append({**r, "risk": risk, "draft_status": flags.get("status"),
                      "dropped_claims": flags.get("dropped_claims", []), "sources": flags.get("sources", []),
                      "web_sources": [{**w, "addable": site_of(w["url"]) is not None} for w in flags.get("web_sources", [])],
                      "timings_ms": flags.get("timings_ms"), "trace_url": tracing.trace_url(trace_id)})
    # stable: risky first (likeliest to be wrong), then guide sections (the home page's entry point, #3), then oldest
    return sorted(items, key=lambda i: (not i["risk"], i["guide"] is None))


def decide(conn: psycopg.Connection, answer_id: int, reviewer_id: int, decision: str,
           final_markdown: str | None, note: str | None, reason: str | None) -> str | None:
    """Apply a decision to a pending answer. Returns the new status, or None if it was not pending (or missing)."""
    status = {"approve": "approved", "edit": "edited", "reject": "rejected"}[decision]
    with conn.transaction():
        row = conn.execute(
            "UPDATE answers SET status = %s, reviewed_by = %s, reviewed_at = now(), review_note = %s,"
            " review_reason = %s,"
            " final_markdown = CASE %s WHEN 'approve' THEN draft_markdown WHEN 'edit' THEN %s ELSE NULL END"
            " WHERE id = %s AND status = 'pending_review' AND draft_markdown IS NOT NULL RETURNING status",
            (status, reviewer_id, note, reason, decision, final_markdown, answer_id),
        ).fetchone()
    return row[0] if row else None


def draft_of(conn: psycopg.Connection, answer_id: int) -> str | None:
    row = conn.execute("SELECT draft_markdown FROM answers WHERE id = %s", (answer_id,)).fetchone()
    return row[0] if row else None


def drafting(conn: psycopg.Connection, answer_id: int) -> bool | None:
    """Whether the answer is still being drafted; None when there is no such answer."""
    row = conn.execute("SELECT draft_markdown IS NULL FROM answers WHERE id = %s", (answer_id,)).fetchone()
    return row[0] if row else None


def recent(conn: psycopg.Connection, limit: int) -> list[dict]:
    """Released (approved/edited) answers, newest reviewed first. Guide-section answers are left out: they already
    appear on their guide pages, and the home page lists those guides just above (#10)."""
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT a.id, a.question, r.name AS reviewed_by, a.reviewed_at"
        " FROM answers a LEFT JOIN users r ON r.id = a.reviewed_by"
        " WHERE a.status IN ('approved', 'edited')"
        " AND NOT EXISTS (SELECT 1 FROM guide_sections gs WHERE gs.answer_id = a.id)"
        " ORDER BY a.reviewed_at DESC, a.id DESC LIMIT %s", (limit,),
    ).fetchall()


def get_answer(conn: psycopg.Connection, answer_id: int, role: str) -> dict | None:
    """Researchers see sources while pending and the final text only after approval; reviewers see everything."""
    a = conn.cursor(row_factory=dict_row).execute(
        "SELECT a.*, r.name AS reviewer_name FROM answers a LEFT JOIN users r ON r.id = a.reviewed_by WHERE a.id = %s",
        (answer_id,),
    ).fetchone()
    if not a:
        return None
    law = [x["distance"] for x in a["flags"].get("sources", []) if x.get("kind") != "decision" and x.get("distance") is not None]
    from app.ask import GATE_MAX_DISTANCE

    view = {"id": a["id"], "question": a["question"], "status": a["status"], "created_at": a["created_at"],
            "sources": a["flags"].get("sources", []), "web_fallback": bool(a["flags"].get("web_fallback")),
            "library_match": bool(law) and min(law) <= GATE_MAX_DISTANCE}
    if a["status"] == "pending_review":
        view["message"] = "Awaiting review"
    elif a["status"] in ("approved", "edited"):
        view |= {"final_markdown": a["final_markdown"], "claims": released_claims(a), "edited": a["status"] == "edited",
                 "reviewed_by": a["reviewer_name"], "reviewed_at": a["reviewed_at"]}
    else:
        view |= {"review_reason": a["review_reason"], "reviewed_by": a["reviewer_name"], "reviewed_at": a["reviewed_at"]}
    if role == "reviewer":
        # "claims" stay the ones shown under the text (kept claims once released, #57); the draft's are draft_claims
        view |= {"draft_markdown": a["draft_markdown"], "claims": view.get("claims", a["claims"]),
                 "draft_claims": a["claims"], "review_note": a["review_note"],
                 "risk": risk_reasons(a["flags"]), "dropped_claims": a["flags"].get("dropped_claims", [])}
    if view.get("claims"):
        view["sources"] = hide_quoted_snippets(view["sources"], view["claims"], excerpt_only_slugs(conn))
    return view


def released_claims(a: dict) -> list[dict]:
    """Claims a researcher sees: all of an approved answer's; of an edited one, only those whose quote the reviewer
    kept in the final text (#57). Computed at read time so the draft's claims stay whole for reviewers and evals."""
    if a["status"] != "edited":
        return a["claims"]
    from app.ask import normalize

    final = normalize(re.sub(r"(?m)^\s*>\s?", "", a["final_markdown"] or ""))  # a reflowed quote keeps its > marks
    return [c for c in a["claims"] if normalize(c.get("quote", "")) in final]


def hide_quoted_snippets(sources: list[dict], claims: list[dict], excerpt_slugs: set[str]) -> list[dict]:
    """A page that quotes an excerpt-only section shows no snippet of it too (quote + snippet could pass the cap,
    #56); the citation and link stay."""
    from app.ask import section_key

    quoted = {section_key(c["source"]) for c in claims if c.get("source", {}).get("slug") in excerpt_slugs}
    return [{**s, "snippet": ""} if s.get("slug") in excerpt_slugs and section_key(s) in quoted else s
            for s in sources]


def edit_distance(draft: str, final: str) -> float:
    """0 = unchanged, 1 = completely rewritten (1 - difflib similarity ratio)."""
    return round(1 - difflib.SequenceMatcher(None, draft or "", final or "").ratio(), 3)


def _decided(conn: psycopg.Connection, answer_id: int) -> dict:
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT id, question, status, draft_markdown, final_markdown, review_reason, review_note, trace_id,"
        " extract(epoch FROM reviewed_at - created_at) AS seconds FROM answers WHERE id = %s", (answer_id,),
    ).fetchone()


def log_decision(conn: psycopg.Connection, answer_id: int) -> None:
    """Scores on the answer's Langfuse trace; edited/rejected answers also become gold candidates."""
    a = _decided(conn, answer_id)
    tracing.score(a["trace_id"], "review_decision", a["status"], data_type="CATEGORICAL")
    tracing.score(a["trace_id"], "time_to_review_s", float(a["seconds"]), data_type="NUMERIC")
    if a["status"] in ("approved", "edited"):
        tracing.score(a["trace_id"], "edit_distance", edit_distance(a["draft_markdown"], a["final_markdown"]),
                      data_type="NUMERIC", comment=a["review_note"])
    if a["status"] == "rejected":
        tracing.score(a["trace_id"], "review_reason", a["review_reason"], data_type="CATEGORICAL")
    if a["status"] in ("edited", "rejected"):
        append_candidate(conn, answer_id)


def append_candidate(conn: psycopg.Connection, answer_id: int) -> bool:
    """Append once per answer id; returns False if it was already there."""
    if CANDIDATES_PATH.exists() and any(json.loads(l)["answer_id"] == answer_id
                                        for l in CANDIDATES_PATH.read_text().splitlines() if l.strip()):
        return False
    a = _decided(conn, answer_id)
    CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CANDIDATES_PATH.open("a") as f:
        f.write(json.dumps({"answer_id": a["id"], "question": a["question"], "decision": a["status"],
                            # a git-tracked file: never more than an excerpt of a City by-law (#56)
                            "draft_markdown": withhold_excerpts(conn, a["draft_markdown"]),
                            "final_markdown": withhold_excerpts(conn, a["final_markdown"]),
                            "review_reason": a["review_reason"], "review_note": a["review_note"]},
                           ensure_ascii=False) + "\n")
    return True
