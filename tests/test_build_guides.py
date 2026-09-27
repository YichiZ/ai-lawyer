from app.ask import AskResult, store_answer
from scripts.build_guides import sync_section


def _answer(conn, question: str) -> int:
    return store_answer(conn, question, None, AskResult("drafted", "Draft.", [], []), [], {})


def _section(conn):
    return conn.execute("SELECT question, answer_id FROM guide_sections WHERE guide_slug = 'g' AND heading = 'Deadlines'").fetchone()


def _setup(conn, status: str = "pending_review") -> int:
    conn.execute("INSERT INTO guides (slug, title, intro, sort_order) VALUES ('g', 'G', 'Intro.', 1)")
    old = _answer(conn, "Old?")
    conn.execute("UPDATE answers SET status = %s WHERE id = %s", (status, old))
    conn.execute("INSERT INTO guide_sections (guide_slug, heading, question, answer_id, sort_order)"
                 " VALUES ('g', 'Deadlines', 'Old?', %s, 1)", (old,))
    return old


def test_unchanged_question_is_skipped(conn):
    old = _setup(conn)
    assert sync_section(conn, "g", "Deadlines", "Old?", 1, lambda q: 1 / 0) is None
    assert _section(conn) == ("Old?", old)


def test_changed_question_redrafts_unreviewed_section(conn):
    old = _setup(conn)
    new = sync_section(conn, "g", "Deadlines", "New?", 1, lambda q: _answer(conn, q))
    assert _section(conn) == ("New?", new)
    assert conn.execute("SELECT 1 FROM answers WHERE id = %s", (old,)).fetchone() is None


def test_changed_question_leaves_reviewed_section(conn):
    old = _setup(conn, status="approved")
    assert sync_section(conn, "g", "Deadlines", "New?", 1, lambda q: 1 / 0) is None
    assert _section(conn) == ("Old?", old)


def test_missing_section_is_drafted(conn):
    conn.execute("INSERT INTO guides (slug, title, intro, sort_order) VALUES ('g', 'G', 'Intro.', 1)")
    new = sync_section(conn, "g", "Deadlines", "New?", 1, lambda q: _answer(conn, q))
    assert _section(conn) == ("New?", new)
