import json

import pytest

from ingest.statutes import load_document, parse_law
from test_statutes import LAW, SECTIONS, row


def counts(conn):
    return conn.execute("SELECT (SELECT count(*) FROM documents), (SELECT count(*) FROM sections)").fetchone()


def test_load_inserts_document_and_tree(conn):
    parsed = parse_law(row(), LAW)
    assert load_document(conn, parsed) == "inserted"
    assert counts(conn) == (1, len(parsed.sections))
    parent_pin = conn.execute(
        "SELECT p.pinpoint FROM sections s JOIN sections p ON p.id = s.parent_id WHERE s.pinpoint = 's-15-2'"
    ).fetchone()[0]
    assert parent_pin == "s-15"
    text = conn.execute("SELECT text FROM sections WHERE pinpoint = 's-4'").fetchone()[0]
    assert text == SECTIONS["4"]


def test_reload_is_a_no_op(conn):
    parsed = parse_law(row(), LAW)
    load_document(conn, parsed)
    before = counts(conn)
    assert load_document(conn, parse_law(row(), LAW)) == "unchanged"
    assert counts(conn) == before


def test_changed_source_replaces_sections(conn):
    load_document(conn, parse_law(row(), LAW))
    changed = parse_law(row(unofficial_sections_en=json.dumps({**SECTIONS, "4": "New text."})), LAW)
    assert load_document(conn, changed) == "updated"
    assert counts(conn) == (1, len(changed.sections))
    assert conn.execute("SELECT text FROM sections WHERE pinpoint = 's-4'").fetchone()[0] == "New text."


def test_failure_mid_document_leaves_no_rows(conn):
    parsed = parse_law(row(), LAW)
    parsed.sections[-1]["parent"] = "no-such-parent"  # corrupt the tree after some rows were inserted
    with pytest.raises(KeyError):
        load_document(conn, parsed)
    assert counts(conn) == (0, 0)
