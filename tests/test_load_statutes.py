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


def _chunks(conn, slug):
    """Chunk the loaded document as ingest does; returns {chunk pinpoint: "c<id>"}."""
    from ingest.chunks import load_sections, plan_chunks, sync_chunks

    doc = conn.execute("SELECT id FROM documents WHERE slug = %s", (slug,)).fetchone()[0]
    sync_chunks(conn, doc, plan_chunks("Test Act", load_sections(conn, doc)))
    return {pin: f"c{cid}" for cid, pin in conn.execute("SELECT id, pinpoint FROM chunks WHERE document_id = %s", (doc,))}


def claim_at(chunks, chunk_pin, quote):
    """A verified claim as run_ask hands it to refine: the source is the retrieved chunk's."""
    source = {"slug": "test-act", "pinpoint": chunk_pin, "display": "x", "url": f"/laws/test-act/{chunk_pin}",
              "citation": {"title": "Test Act", "reference": "x", "text": "x"}}
    return {"text": "x", "chunk_id": chunks[chunk_pin], "quote": quote, "source": source}


def test_claims_get_the_subsection_pinpoint_that_holds_the_quote(conn):
    from app.ask import pinpoint_claims

    load_document(conn, parse_law(row(), LAW))
    chunks = _chunks(conn, "test-act")
    claims = [claim_at(chunks, "s-15", q) for q in (
        "No proceeding after the 15th anniversary", "Despite subsection (2), none.",
        "no proceeding.\n(2) No proceeding after",  # spans two subsections
    )]
    out = pinpoint_claims(conn, claims)
    assert [c["source"]["pinpoint"] for c in out] == ["s-15-2", "s-15-2.1", "s-15"]
    assert out[0]["source"]["display"] == "s. 15(2)"
    assert out[0]["source"]["citation"]["reference"] == "SO 2002, c 24, Sched B, s 15(2)"
    assert out[0]["source"]["url"] == "/laws/test-act/s-15-2"
    assert claims[0]["source"]["pinpoint"] == "s-15"  # input not mutated


def test_claims_in_a_split_section_get_the_subsection_that_holds_the_quote(conn):
    """Issue #1: a long section's chunks are pinpointed at their first subsection (s-42-1, s-42-5, ...), and the claim
    kept that pinpoint instead of the subsection holding its quote."""
    from app.ask import pinpoint_claims

    filler = " ".join(["words"] * 120)  # ~730 chars per subsection: eight of them force a split
    text = "\n".join(f"({n}) Rule number {n} says {filler}." for n in range(1, 9))
    load_document(conn, parse_law(row(unofficial_sections_en=json.dumps({**SECTIONS, "42": text})), LAW))
    chunks = _chunks(conn, "test-act")
    later = [p for p in chunks if p.startswith("s-42-") and p != "s-42-1"]
    assert "s-42-1" in chunks and later  # the section really is split

    last = later[-1]
    out = pinpoint_claims(conn, [
        claim_at(chunks, "s-42-1", "Rule number 2 says words"),
        claim_at(chunks, "s-42-1", "words.\n(2) Rule number 2"),  # spans (1)-(2): the section
        claim_at(chunks, last, "Rule number 8 says words"),
    ])
    assert [c["source"]["pinpoint"] for c in out] == ["s-42-2", "s-42", "s-42-8"]
    assert out[1]["source"]["url"] == "/laws/test-act/s-42" and out[1]["source"]["display"] == "s. 42"
