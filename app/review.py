"""Human review: every drafted answer waits in pending_review until a reviewer approves, edits or rejects it."""
import psycopg
from psycopg.rows import dict_row

from app import tracing

REJECT_REASONS = ("wrong_law", "missing_authority", "unsupported_claim", "out_of_scope")
REFUSAL_STATUSES = ("not_found", "out_of_scope", "unverified")


def risk_reasons(flags: dict) -> list[str]:
    reasons = []
    if flags.get("status") in REFUSAL_STATUSES:
        reasons.append(flags["status"])
    if flags.get("dropped_claims"):
        reasons.append("dropped_claims")
    if flags.get("retried"):
        reasons.append("retried")
    return reasons


def queue(conn: psycopg.Connection) -> list[dict]:
    rows = conn.cursor(row_factory=dict_row).execute(
        "SELECT a.id, a.question, a.draft_markdown, a.claims, a.flags, a.created_at, a.trace_id, u.name AS asked_by"
        " FROM answers a LEFT JOIN users u ON u.id = a.asked_by WHERE a.status = 'pending_review'"
        " ORDER BY a.created_at, a.id"
    ).fetchall()
    items = []
    for r in rows:
        flags, trace_id = r.pop("flags"), r.pop("trace_id")
        risk = risk_reasons(flags)
        items.append({**r, "risk": risk, "draft_status": flags.get("status"),
                      "dropped_claims": flags.get("dropped_claims", []), "sources": flags.get("sources", []),
                      "timings_ms": flags.get("timings_ms"), "trace_url": tracing.trace_url(trace_id)})
    return sorted(items, key=lambda i: (not i["risk"],))  # stable: risky first, then oldest first


def decide(conn: psycopg.Connection, answer_id: int, reviewer_id: int, decision: str,
           final_markdown: str | None, note: str | None, reason: str | None) -> str | None:
    """Apply a decision to a pending answer. Returns the new status, or None if it was not pending (or missing)."""
    status = {"approve": "approved", "edit": "edited", "reject": "rejected"}[decision]
    with conn.transaction():
        row = conn.execute(
            "UPDATE answers SET status = %s, reviewed_by = %s, reviewed_at = now(), review_note = %s,"
            " review_reason = %s,"
            " final_markdown = CASE %s WHEN 'approve' THEN draft_markdown WHEN 'edit' THEN %s ELSE NULL END"
            " WHERE id = %s AND status = 'pending_review' RETURNING status",
            (status, reviewer_id, note, reason, decision, final_markdown, answer_id),
        ).fetchone()
    return row[0] if row else None


def exists(conn: psycopg.Connection, answer_id: int) -> bool:
    return conn.execute("SELECT 1 FROM answers WHERE id = %s", (answer_id,)).fetchone() is not None


def get_answer(conn: psycopg.Connection, answer_id: int, role: str) -> dict | None:
    """Researchers see sources while pending and the final text only after approval; reviewers see everything."""
    a = conn.cursor(row_factory=dict_row).execute(
        "SELECT a.*, r.name AS reviewer_name FROM answers a LEFT JOIN users r ON r.id = a.reviewed_by WHERE a.id = %s",
        (answer_id,),
    ).fetchone()
    if not a:
        return None
    view = {"id": a["id"], "question": a["question"], "status": a["status"], "created_at": a["created_at"],
            "sources": a["flags"].get("sources", [])}
    if a["status"] == "pending_review":
        view["message"] = "Awaiting review"
    elif a["status"] in ("approved", "edited"):
        view |= {"final_markdown": a["final_markdown"], "claims": a["claims"], "edited": a["status"] == "edited",
                 "reviewed_by": a["reviewer_name"], "reviewed_at": a["reviewed_at"]}
    else:
        view |= {"review_reason": a["review_reason"], "reviewed_by": a["reviewer_name"], "reviewed_at": a["reviewed_at"]}
    if role == "reviewer":
        view |= {"draft_markdown": a["draft_markdown"], "claims": a["claims"], "review_note": a["review_note"],
                 "risk": risk_reasons(a["flags"]), "dropped_claims": a["flags"].get("dropped_claims", [])}
    return view
