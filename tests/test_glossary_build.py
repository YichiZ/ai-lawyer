
from ingest.glossary_build import build_prompt, load_terms, resolve_source, upsert_definitions
from ingest.statutes import load_document, parse_law
from test_statutes import LAW, row


def test_load_terms(tmp_path):
    p = tmp_path / "t.tsv"
    p.write_text("# comment\nclaim\ttest-act\ts-1\noccupier\n")
    assert load_terms(p) == [("claim", "test-act", "s-1"), ("occupier", None, None)]


def test_resolve_source_fixed_and_statutory(conn):
    load_document(conn, parse_law(row(), LAW))
    assert resolve_source(conn, "claim", "test-act", "s-4")[:2] == ("test-act", "s-4")
    slug, pin, text = resolve_source(conn, "claim", None, None)  # “claim” means ... in s. 1
    assert (slug, pin) == ("test-act", "s-1") and "means a claim" in text
    assert resolve_source(conn, "unicorn", None, None) is None


def test_prompt_mentions_term_source_and_text():
    p = build_prompt("claim", "Test Act, s. 1", "“claim” means a claim to remedy an injury;")
    assert "claim" in p and "Test Act, s. 1" in p and "remedy an injury" in p


def test_upsert_is_idempotent(conn):
    load_document(conn, parse_law(row(), LAW))
    terms = [("claim", None, None)]
    assert upsert_definitions(conn, terms, lambda p: "A request to fix a harm.", workers=1) == 1
    assert upsert_definitions(conn, terms, lambda p: "other", workers=1) == 0
    assert conn.execute("SELECT plain_definition, source_pinpoint FROM glossary_terms WHERE term = 'claim'").fetchone() == ("A request to fix a harm.", "s-1")
