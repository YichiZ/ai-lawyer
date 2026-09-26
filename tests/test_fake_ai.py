from app.ask import PROMPT, verify_claims
from app.fake_ai import FakeAI
from ingest.chunks import embed_pending, plan_chunks, sync_chunks
from ingest.statutes import load_document, parse_law
from test_statutes import LAW, row


def test_fake_ai_is_deterministic_and_verifiable(conn):
    load_document(conn, parse_law(row(), LAW))
    doc_id = conn.execute("SELECT id FROM documents WHERE slug = 'test-act'").fetchone()[0]
    secs = conn.execute("SELECT id, pinpoint, kind, heading, text, NULL FROM sections WHERE document_id = %s ORDER BY sort_order", (doc_id,)).fetchall()
    sync_chunks(conn, doc_id, plan_chunks("Test Act", [dict(zip(("id", "pinpoint", "kind", "heading", "text", "parent"), r)) for r in secs]))
    embed_pending(conn, lambda t: [float(len(t) % 7 + 1)] + [0.0] * 1535, model="fake", workers=1)

    ai = FakeAI(lambda: conn)
    v = ai.embed_query("second anniversary proceeding")
    assert len(v) == 1536 and v == ai.embed_query("second anniversary proceeding")

    passages = "[c7] Test Act, s 4\nUnless this Act provides otherwise, a proceeding shall not be commenced after the second anniversary.\n\n[c8] x\nOther."
    out = ai.generate(PROMPT.format(question="q", passages=passages, feedback=""), {})
    ok, dropped = verify_claims(out["claims"], {"c7": "Unless this Act provides otherwise, a proceeding shall not be commenced after the second anniversary.", "c8": "Other."})
    assert out["in_scope"] is True and len(ok) == 1 and dropped == []
