from ingest.glossary_build import build_prompt, define, is_non_answer, load_terms, rejection, resolve_source, upsert_definitions
from ingest.statutes import load_document, parse_law
from test_statutes import LAW, row

NON_ANSWER = "The provided text does not define the term."
GOOD = "A request to fix a harm."


def test_load_terms(tmp_path):
    p = tmp_path / "t.tsv"
    p.write_text("# comment\nclaim\ttest-act\ts-1\noccupier\n")
    assert load_terms(p) == [("claim", "test-act", "s-1"), ("occupier", None, None)]


def test_resolve_source_prefers_a_definition_over_the_curated_section(conn):
    load_document(conn, parse_law(row(), LAW))
    slug, pin, text = resolve_source(conn, "claim", "test-act", "s-4")  # s. 4 uses "claim", s. 1 defines it
    assert (slug, pin) == ("test-act", "s-1") and "means a claim" in text
    assert resolve_source(conn, "claim", "test-act", "s-1")[:2] == ("test-act", "s-1")
    assert resolve_source(conn, "claim", None, None)[:2] == ("test-act", "s-1")
    assert resolve_source(conn, "proceeding", "test-act", "s-4")[:2] == ("test-act", "s-4")  # no definition: curated
    assert resolve_source(conn, "unicorn", None, None) is None


def test_resolve_source_ignores_definitions_quoted_in_decisions(conn):
    load_document(conn, parse_law(row(), LAW))
    conn.execute("UPDATE documents SET kind = 'decision' WHERE slug = 'test-act'")
    assert resolve_source(conn, "claim", None, None) is None
    assert resolve_source(conn, "claim", "test-act", "s-4")[:2] == ("test-act", "s-4")


def test_prompt_mentions_term_source_and_text_and_forbids_source_talk():
    p = build_prompt("claim", "Test Act, s. 1", "“claim” means a claim to remedy an injury;")
    assert "claim" in p and "Test Act, s. 1" in p and "remedy an injury" in p
    assert "the provided text" in p and "Never mention the source" in p


def test_rejection_catches_non_answers_and_source_references():
    assert is_non_answer(NON_ANSWER) and rejection(NON_ANSWER)
    assert rejection("")
    for bad in ("Based on this text, negligence is fault.", "Under this text, damages are money.",
                "Under this section, costs are amounts of a proceeding.", "In this Part, an insurer is licensed.",
                "Under this Act, a spouse is a married person."):
        assert rejection(bad), bad
    for good in ("Negligence is a failure to take reasonable care that causes harm to another person.",
                 "Under Ontario's Negligence Act, each wrongdoer pays in proportion to fault.",
                 "Damages based on the degree of fault are shared.", "Attendant care covers the provision of services."):
        assert rejection(good) is None, good


def fake(answers):
    prompts = []

    def generate(prompt):
        prompts.append(prompt)
        return answers[len(prompts) - 1]
    return generate, prompts


def test_define_retries_once_with_a_stricter_prompt():
    generate, prompts = fake(["Based on this text, a claim is a claim.", f"  {GOOD}\n"])
    assert define("claim", "PROMPT", generate) == GOOD
    assert len(prompts) == 2 and prompts[1].startswith("PROMPT") and "rejected because it referred to the source" in prompts[1]


def test_define_strips_markdown_and_stored_markdown_fails_the_check():
    generate, _ = fake([f"**Claim** is {GOOD}"])
    assert define("claim", "PROMPT", generate) == f"Claim is {GOOD}"
    assert rejection("**Claim** is a request.") == rejection("Filed under the *Juries Act*.") == "used Markdown formatting"


def test_define_drops_a_term_that_fails_twice(capsys):
    generate, prompts = fake([NON_ANSWER, NON_ANSWER])
    assert define("claim", "PROMPT", generate) is None
    assert len(prompts) == 2 and "dropped 'claim'" in capsys.readouterr().out


def test_upsert_is_idempotent(conn):
    load_document(conn, parse_law(row(), LAW))
    terms = [("claim", None, None)]
    assert upsert_definitions(conn, terms, lambda p: GOOD, workers=1) == 1
    assert upsert_definitions(conn, terms, lambda p: "other", workers=1) == 0
    assert conn.execute("SELECT plain_definition, source_pinpoint FROM glossary_terms WHERE term = 'claim'").fetchone() == (GOOD, "s-1")


def test_upsert_never_stores_a_non_answer(conn):
    load_document(conn, parse_law(row(), LAW))
    conn.execute("INSERT INTO glossary_terms (term, plain_definition, source_slug, source_pinpoint) VALUES"
                 " ('proceeding', %s, 'test-act', 's-4'), ('claim', 'Based on this text, a claim.', 'test-act', 's-1')",
                 (NON_ANSWER,))
    terms = [("claim", None, None), ("proceeding", "test-act", "s-4"), ("limitation", "test-act", "s-4")]
    answers = {"claim": [GOOD], "proceeding": [NON_ANSWER, NON_ANSWER], "limitation": ["Based on the text, x.", "A time limit."]}

    def generate(prompt):
        term = prompt.split('"')[1]
        return answers[term].pop(0)
    assert upsert_definitions(conn, terms, generate, workers=1) == 3
    rows = dict(conn.execute("SELECT term, plain_definition FROM glossary_terms"))
    assert rows == {"claim": GOOD, "limitation": "A time limit."}  # stale non-answer for "proceeding" deleted
    assert not any(rejection(d) for d in rows.values())


def test_upsert_redo_rewrites_and_keeps_a_good_definition_if_the_rewrite_fails(conn):
    load_document(conn, parse_law(row(), LAW))
    conn.execute("INSERT INTO glossary_terms (term, plain_definition, source_slug, source_pinpoint) VALUES"
                 " ('claim', 'Old but valid.', 'test-act', 's-4')")
    assert upsert_definitions(conn, [("claim", "test-act", "s-4")], lambda p: NON_ANSWER, workers=1,
                              redo=frozenset({"claim"})) == 1
    assert conn.execute("SELECT plain_definition FROM glossary_terms WHERE term = 'claim'").fetchone()[0] == "Old but valid."
    upsert_definitions(conn, [("claim", "test-act", "s-4")], lambda p: GOOD, workers=1, redo=frozenset({"claim"}))
    assert conn.execute("SELECT plain_definition, source_pinpoint FROM glossary_terms WHERE term = 'claim'").fetchone() == (GOOD, "s-1")
