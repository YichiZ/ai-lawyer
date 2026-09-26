import pytest

from ingest.summaries import PROMPT_VERSION, build_prompt, eligible, source_hash, summarize_pending
from ingest.statutes import load_document, parse_law
from test_statutes import LAW, row


@pytest.mark.parametrize(
    "text, ok",
    [("[blank]", False), ("Repealed: 2015, c. 14, s. 30.", False), ("Omitted (amends or repeals other Acts).", False),
     ("Revoked: O. Reg. 709/21, s. 5.", False), ("Short.", False),
     ("Unless this Act provides otherwise, a proceeding shall not be commenced after the second anniversary.", True)],
)
def test_eligible(text, ok):
    assert eligible({"kind": "section", "text": text}) is ok


def test_parts_and_subsections_not_eligible():
    long = "x " * 50
    assert not eligible({"kind": "part", "text": long}) and not eligible({"kind": "subsection", "text": long})


def test_prompt_has_rules_and_text():
    p = build_prompt("Limitations Act, 2002", "s. 4", "Basic limitation period", "Unless this Act provides otherwise...")
    assert "grade 8" in p and "not legal advice" in p.lower() and "Unless this Act provides otherwise..." in p


def test_hash_depends_on_text_and_prompt_version():
    assert source_hash("a") != source_hash("b") and len(source_hash("a")) == 64
    assert PROMPT_VERSION >= 1


def test_summarize_pending_is_idempotent_and_redoes_changed_text(conn):
    load_document(conn, parse_law(row(), LAW))
    calls = []
    n = summarize_pending(conn, lambda p: calls.append(p) or "Plain summary.", workers=1)
    assert n == len(calls) == 2  # s-4 and s-15; s-1 (55 chars) and placeholders are skipped
    assert summarize_pending(conn, lambda p: "again", workers=1) == 0
    conn.execute("UPDATE sections SET text = text || ' Changed.' WHERE pinpoint = 's-4'")
    assert summarize_pending(conn, lambda p: "New summary.", workers=1) == 1
    assert conn.execute("SELECT plain_summary FROM sections WHERE pinpoint = 's-4'").fetchone()[0] == "New summary."
