import pytest

from app.ask import (
    CLAIMS_SCHEMA,
    GATE_MAX_DISTANCE,
    AskResult,
    Retrieved,
    compose_draft,
    library_titles,
    normalize,
    out_of_scope_message,
    result_flags,
    rrf,
    run_ask,
    verify_claims,
)
from app.authorities import SECONDARY_LABEL


# --- pure logic ---

def test_rrf_fuses_ranks():
    # a: rank 1 in both; b: rank 2 keyword only; c: rank 2 vector only; d: rank 3 in both
    fused = rrf([["a", "b", "d"], ["a", "c", "d"]], k=60)
    assert [cid for cid, _ in fused][:2] == ["a", "d"]
    assert fused[0][1] == pytest.approx(2 / 61)


def test_rrf_ties_are_stable():
    assert [cid for cid, _ in rrf([["x", "y"], ["y", "x"]])] == ["x", "y"]


def test_normalize_whitespace_and_quote_marks():
    assert normalize("  the  “claim”\n was  discovered’s ") == 'the "claim" was discovered\'s'


CHUNKS = {
    "c1": "Unless this Act provides otherwise, a proceeding shall not be commenced in respect of a claim after the second\nanniversary of the day on which the claim was discovered.",
    "c2": "The owner of a dog is liable for damages resulting from a bite or attack by the dog on another person.",
}


def claim(quote, chunk_id="c1", text="Two years from discovery."):
    return {"text": text, "chunk_id": chunk_id, "quote": quote}


def test_verify_exact_and_whitespace_variants():
    ok, dropped = verify_claims([claim("a proceeding shall not be commenced in respect of a claim after the second anniversary")], CHUNKS)
    assert len(ok) == 1 and dropped == []


def test_verify_curly_quotes_match_straight():
    chunks = {"c1": 'In this Act, "claim" means a claim to remedy an injury.'}
    ok, _ = verify_claims([claim("In this Act, “claim” means a claim to remedy an injury")], chunks)
    assert len(ok) == 1


@pytest.mark.parametrize(
    "bad, reason",
    [
        (claim("a proceeding may be commenced at any time"), "quote_not_in_chunk"),  # paraphrase
        (claim("The owner of a dog is liable", chunk_id="c1"), "quote_not_in_chunk"),  # wrong chunk
        (claim("anything at all", chunk_id="c9"), "chunk_not_retrieved"),
        (claim("claim"), "quote_too_short"),
    ],
)
def test_verify_drops_bad_claims(bad, reason):
    ok, dropped = verify_claims([bad], CHUNKS)
    assert ok == [] and dropped[0]["reason"] == reason


def test_compose_draft_uses_verified_quotes_only():
    source = {"citation": {"title": "Limitations Act, 2002", "reference": "SO 2002, c 24, Sched B, s 4"}}
    md = compose_draft("You generally have two years.", [{**claim("a proceeding shall not be commenced"), "source": source}])
    assert md.startswith("You generally have two years.")
    assert "**What the law says**" in md
    assert "> a proceeding shall not be commenced" in md
    assert "*Limitations Act, 2002*, SO 2002, c 24, Sched B, s 4" in md


# --- orchestration with fakes ---

def hit(cid, distance, text=None):
    return Retrieved(chunk_id=cid, text=text or CHUNKS[cid], distance=distance, source={"citation": {"title": "T", "reference": "R"}})


class FakeLLM:
    def __init__(self, responses):
        self.responses, self.prompts = list(responses), []

    def __call__(self, prompt, schema):
        self.prompts.append(prompt)
        return self.responses.pop(0)


def test_gate_refuses_without_model_call():
    llm = FakeLLM([])
    result = run_ask("How do I appeal a BC speeding ticket?", [hit("c2", GATE_MAX_DISTANCE + 0.1)], llm)
    assert result.status == "not_found" and llm.prompts == []
    assert "not found in the laws we cover" in result.draft_markdown


def test_verified_answer():
    llm = FakeLLM([{"in_scope": True, "answer": "Two years.", "claims": [claim("a proceeding shall not be commenced in respect of a claim")]}])
    result = run_ask("How long to sue?", [hit("c1", 0.2), hit("c2", 0.3)], llm)
    assert result.status == "drafted" and len(result.claims) == 1 and result.dropped == []
    assert "c1" in llm.prompts[0] and "How long to sue?" in llm.prompts[0]


def test_prompt_says_indexed_amounts_are_not_current():
    """#2: a base figure in "the greater of $X and the prescribed amount" must not be presented as current."""
    llm = FakeLLM([{"in_scope": True, "answer": "x", "claims": [claim("a proceeding shall not be commenced in respect of a claim")]}])
    run_ask("What is the deductible?", [hit("c1", 0.2)], llm)
    prompt = " ".join(llm.prompts[0].split())
    assert "never present the base or dated figure as the current amount" in prompt
    assert "Never calculate a current amount" in prompt


def test_prompt_keeps_indexation_to_the_provisions_scope():
    """#32: an indexing provision limited to an optional benefit or to 1994-1996 accidents must keep that condition."""
    llm = FakeLLM([{"in_scope": True, "answer": "x", "claims": [claim("a proceeding shall not be commenced in respect of a claim")]}])
    run_ask("Are accident benefits indexed?", [hit("c1", 0.2)], llm)
    prompt = " ".join(llm.prompts[0].split())
    assert "with every condition it sets" in prompt
    assert "Never extend an indexing provision to amounts or accidents it does not cover" in prompt


def test_prompt_keeps_each_claim_within_its_quote():
    """#43: a claim that adds a detail from another provision (the 7-day insurer notice) is unfaithful to its quote."""
    llm = FakeLLM([{"in_scope": True, "answer": "x", "claims": [claim("a proceeding shall not be commenced in respect of a claim")]}])
    run_ask("What notice is needed?", [hit("c1", 0.2)], llm)
    prompt = " ".join(llm.prompts[0].split())
    assert "Each claim restates only what its own quote says" in prompt
    assert "Never combine two provisions in one claim" in prompt


def test_retry_once_then_refuse():
    bad = {"in_scope": True, "answer": "x", "claims": [claim("made up words that are not there")]}
    llm = FakeLLM([bad, bad])
    result = run_ask("How long to sue?", [hit("c1", 0.2)], llm)
    assert len(llm.prompts) == 2 and result.status == "unverified"
    assert len(result.dropped) == 2 and result.claims == []


def test_retry_succeeds():
    bad = {"in_scope": True, "answer": "x", "claims": [claim("made up words that are not there")]}
    good = {"in_scope": True, "answer": "Two years.", "claims": [claim("a proceeding shall not be commenced")]}
    result = run_ask("How long to sue?", [hit("c1", 0.2)], FakeLLM([bad, good]))
    assert result.status == "drafted" and result.retried and len(result.dropped) == 1


def test_out_of_scope_refusal():
    llm = FakeLLM([{"in_scope": False, "scope_note": "British Columbia traffic law", "answer": "", "claims": []}])
    result = run_ask("BC speeding ticket appeal?", [hit("c1", 0.2)], llm)
    assert result.status == "out_of_scope" and len(llm.prompts) == 1
    assert "British Columbia traffic law" in result.draft_markdown


@pytest.mark.parametrize("note, topic", [
    ("criminal sentencing", "Criminal sentencing"),
    ("British Columbia traffic law.", "British Columbia traffic law"),
    ("Sentencing for criminal offences (such as impaired driving under the Criminal Code) falls under federal "
     "criminal law rather than Ontario personal-injury law.",
     "Sentencing for criminal offences (such as impaired driving under the Criminal Code)"),
    ("family law other than Family Law Act s. 61 claims; spousal support", "Family law other than Family Law Act s. 61 claims"),
    ("", "Another area of law"),
    (None, "Another area of law"),
])
def test_out_of_scope_message_is_one_clean_sentence(note, topic):
    assert out_of_scope_message(note) == (
        f"This guide covers Ontario personal-injury law only. Topic of this question: {topic}.")


def test_refine_runs_on_verified_claims_before_composing():
    llm = FakeLLM([{"in_scope": True, "answer": "Two years.", "claims": [claim("a proceeding shall not be commenced in respect of a claim")]}])
    refine = lambda cs: [{**c, "source": {**c["source"], "citation": {"title": "T", "reference": "R(6)"}}} for c in cs]
    result = run_ask("How long to sue?", [hit("c1", 0.2)], llm, refine)
    assert "— *T*, R(6)" in result.draft_markdown and result.claims[0]["source"]["citation"]["reference"] == "R(6)"


def test_weighted_rrf_can_favour_vector_list():
    keyword, vector = ["k1", "both"], ["v1", "both"]
    plain = [cid for cid, _ in rrf([keyword, vector])]
    assert plain[0] == "both"  # in both lists at rank 2 beats rank 1 in one
    weighted = [cid for cid, _ in rrf([keyword, vector], weights=[0.01, 1.0])]  # k=60 flattens ranks: tiny weight needed
    assert weighted[0] == "v1"


@pytest.mark.parametrize("kind", ["decision", "web"])
def test_gate_ignores_decision_and_web_hits(kind):
    near = Retrieved("c9", "Something related.", 0.05, {"citation": {"title": "T", "reference": "R"}, "kind": kind})
    far_law = hit("c1", GATE_MAX_DISTANCE + 0.1)
    llm = FakeLLM([])
    assert run_ask("q?", [far_law, near], llm).status == "not_found" and llm.prompts == []


CRINSON = "No action shall be maintained unless notice in writing of the claim is served within 10 days after the occurrence."


def test_statute_quoted_only_by_a_decision_is_labelled_and_flagged():
    decision = Retrieved("c9", CRINSON, 0.25, {"title": "Crinson v. Toronto (City)", "kind": "decision",
                                               "citation": {"title": "Crinson v. Toronto (City)", "reference": "2010 ONCA 44 at para 6"}})
    llm = FakeLLM([{"in_scope": True, "answer": "Under s. 44(10) of the Municipal Act, 2001, notice is due within 10 days.",
                    "claims": [claim("notice in writing of the claim is served within 10 days", chunk_id="c9")]}])
    result = run_ask("Notice under the Municipal Act?", [hit("c1", 0.2), decision], llm)
    assert result.status == "drafted" and result.draft_markdown.startswith(SECONDARY_LABEL + "\n\n")
    assert result.secondary_statute == ["Municipal Act, 2001"]


def test_decision_quoting_a_law_we_hold_is_not_labelled():
    decision = Retrieved("c9", CRINSON, 0.25, {"title": "Crinson v. Toronto (City)", "kind": "decision",
                                               "citation": {"title": "Crinson v. Toronto (City)", "reference": "2010 ONCA 44 at para 6"}})
    llm = FakeLLM([{"in_scope": True, "answer": "Under the Highway Traffic Act, notice is due within 10 days.",
                    "claims": [claim("notice in writing of the claim is served within 10 days", chunk_id="c9")]}])
    result = run_ask("Notice?", [hit("c1", 0.2), decision], llm, library_titles=["Highway Traffic Act"])
    assert not result.draft_markdown.startswith(SECONDARY_LABEL) and result.secondary_statute == []


def test_library_titles_lists_laws_not_decisions(conn):
    conn.execute("INSERT INTO documents (sha256, kind, slug, title, short_name, citation, source) VALUES"
                 " ('l1', 'statute', 'hta', 'Highway Traffic Act', 'HTA', 'RSO 1990, c H8', 't'),"
                 " ('l2', 'decision', 'crinson', 'Crinson v. Toronto (City)', NULL, '2010 ONCA 44', 't')")
    titles = library_titles(conn)
    assert {"Highway Traffic Act", "HTA", "RSO 1990, c H8"} <= set(titles)
    assert "Crinson v. Toronto (City)" not in titles and None not in titles


def test_statute_sourced_answer_is_not_labelled():
    law = Retrieved("c1", CHUNKS["c1"], 0.2, {"title": "Limitations Act, 2002", "kind": "statute",
                                                 "citation": {"title": "Limitations Act, 2002", "reference": "s 4"}})
    llm = FakeLLM([{"in_scope": True, "answer": "Under the Limitations Act, 2002, the period is two years.",
                    "claims": [claim("a proceeding shall not be commenced in respect of a claim")]}])
    result = run_ask("How long to sue?", [law], llm)
    assert not result.draft_markdown.startswith(SECONDARY_LABEL) and result.secondary_statute == []


def test_advice_seeking_flag_from_the_model():
    """#7: the drafting call also says whether the question asks for advice on the asker's own facts."""
    out = {"in_scope": True, "answer": "Two years.", "claims": [claim("a proceeding shall not be commenced")]}
    llm = FakeLLM([{**out, "advice_seeking": True}, out])
    assert run_ask("I slipped last week. Do I have a case?", [hit("c1", 0.2)], llm).advice_seeking is True
    assert run_ask("How long to sue?", [hit("c1", 0.2)], llm).advice_seeking is False
    assert "advice_seeking" in CLAIMS_SCHEMA["required"]
    assert "advice_seeking=true" in " ".join(llm.prompts[0].split())


def test_advice_seeking_kept_when_unverified():
    bad = {"in_scope": True, "advice_seeking": True, "answer": "x", "claims": [claim("made up words that are not there")]}
    result = run_ask("Calculate my last day to sue.", [hit("c1", 0.2)], FakeLLM([bad, bad]))
    assert result.status == "unverified" and result.advice_seeking


def test_result_flags_carry_advice_seeking():
    flags = result_flags(AskResult("drafted", "d", advice_seeking=True))
    assert flags["advice_seeking"] is True and flags["status"] == "drafted"


# --- cross-references (#61) ---

def _law_with_references(conn):
    import json

    from ingest.statutes import load_document, parse_law
    from test_load_statutes import _chunks
    from test_statutes import LAW, SECTIONS, row

    s4 = ("Unless this Act provides otherwise, a proceeding shall not be commenced after the second anniversary, "
          "subject to subsection 15 (2). See section 1; section 3 of the Negligence Act does not apply.")
    load_document(conn, parse_law(row(unofficial_sections_en=json.dumps({**SECTIONS, "4": s4})), LAW))
    chunks = _chunks(conn, "test-act")
    text = conn.execute("SELECT text FROM chunks WHERE id = %s", (int(chunks["s-4"][1:]),)).fetchone()[0]
    return chunks, text


def _law_hit(cid, text, kind="statute"):
    return Retrieved(cid, text, 0.1, {"slug": "test-act", "kind": kind, "display": "s. 4",
                                      "citation": {"title": "T", "reference": "R"}})


def test_cross_references_add_the_referenced_chunks_once_in_order(conn):
    from app.ask import with_cross_references

    chunks, s4 = _law_with_references(conn)
    hits = [_law_hit(chunks["s-4"], s4), _law_hit(chunks["s-4"], s4)]  # the same references twice: added once
    out = with_cross_references(conn, hits)
    added = out[len(hits):]
    assert [h.chunk_id for h in added] == [chunks["s-15"], chunks["s-1"]]  # s. 3 of the Negligence Act ignored
    assert all(h.distance is None and h.source["referenced_by"] == chunks["s-4"] for h in added)
    assert all(h.source["referenced_by_display"] == "s. 4" for h in added)  # shown on the answer page
    assert added[0].source["url"] == "/laws/test-act/s-15" and "15th anniversary" in added[0].text
    assert out[:2] == hits and len(hits) == 2  # appended after the ranked hits; input not mutated


def test_cross_references_in_a_list_of_another_laws_sections_are_ignored(conn):
    from app.ask import with_cross_references

    _law_with_references(conn)
    hits = [_law_hit("c999999", "sections 1, 4 and 15 of the Negligence Act, or section 1 and section 15 of the Act")]
    assert with_cross_references(conn, hits) == hits


def test_cross_reference_to_a_repealed_provision_uses_no_slot(conn):
    import json

    from app.ask import with_cross_references
    from ingest.statutes import load_document, parse_law
    from test_load_statutes import _chunks
    from test_statutes import LAW, SECTIONS, row

    load_document(conn, parse_law(row(unofficial_sections_en=json.dumps({**SECTIONS, "1": "Repealed: 2020, c. 1, s. 1."})), LAW))
    chunks = _chunks(conn, "test-act")
    out = with_cross_references(conn, [_law_hit("c999999", "under section 1 and subsection 15 (2)... see section 4")], cap=1)
    assert [h.chunk_id for h in out[1:]] == [chunks["s-4"]]  # s. 1 is a repeal stub; s. 15 is the list's second item


def test_cross_references_respect_the_cap_and_skip_retrieved_chunks(conn):
    from app.ask import with_cross_references

    chunks, s4 = _law_with_references(conn)
    assert [h.chunk_id for h in with_cross_references(conn, [_law_hit(chunks["s-4"], s4)], cap=1)] == [chunks["s-4"], chunks["s-15"]]
    already = [_law_hit(chunks["s-4"], s4), _law_hit(chunks["s-15"], "no references")]
    out = with_cross_references(conn, already)
    assert [h.chunk_id for h in out] == [chunks["s-4"], chunks["s-15"], chunks["s-1"]]
    assert out[1].source["referenced_by"] == chunks["s-4"] and out[1].distance == 0.1  # labelled, rank kept
    assert "referenced_by" not in out[0].source and "referenced_by" not in already[1].source  # not mutated


def test_cross_reference_to_its_own_chunk_is_ignored(conn):
    from app.ask import with_cross_references

    chunks, _ = _law_with_references(conn)
    hits = [_law_hit(chunks["s-15"], "subject to subsection 15 (2)")]
    assert with_cross_references(conn, hits) == hits


def test_cross_references_that_set_the_terms_come_first(conn):
    """mv-16: the top hit (SABS s. 30(1)) lists many amounts by reference and used up the cap before s. 268.1(3)'s
    "in accordance with clause 268 (1.4) (b)" was reached."""
    from app.ask import with_cross_references

    chunks, _ = _law_with_references(conn)
    hits = [_law_hit("c999998", "the amounts in section 1 and section 4"),
            _law_hit("c999999", "revised in accordance with clause 15 (2) (a)")]
    assert [h.chunk_id for h in with_cross_references(conn, hits, cap=1)][2:] == [chunks["s-15"]]


@pytest.mark.parametrize("kind", ["decision", "web"])
def test_cross_references_only_from_laws(conn, kind):
    from app.ask import with_cross_references

    _law_with_references(conn)
    hits = [_law_hit("c999999", "the limit in subsection 15 (2)", kind)]
    assert with_cross_references(conn, hits) == hits


def test_retrieve_for_answer_appends_cross_references(conn, monkeypatch):
    from app import ask

    chunks, s4 = _law_with_references(conn)
    monkeypatch.setattr(ask, "retrieve", lambda conn, q, v, top_k=8, rerank=None, kinds=None:
                        [_law_hit(chunks["s-4"], s4)] if kinds is None else [])
    out = ask.retrieve_for_answer(conn, "how long?", [0.01] * 1536)
    assert [h.chunk_id for h in out] == [chunks["s-4"], chunks["s-15"], chunks["s-1"]]


def test_referenced_passage_is_labelled_for_the_model():
    llm = FakeLLM([{"in_scope": True, "answer": "x", "claims": [claim("a proceeding shall not be commenced in respect of a claim")]}])
    ref = Retrieved("c2", CHUNKS["c2"], None, {"citation": {"title": "T", "reference": "R"}, "referenced_by": "c1"})
    run_ask("How long to sue?", [hit("c1", 0.2), ref], llm)
    assert "[c2] *T*, R (referred to by [c1])" in llm.prompts[0]
    assert 'A passage marked "referred to by [cN]"' in llm.prompts[0]


# --- excerpt-only sources (#56) ---

def _sentences(first, last):
    """Distinct sentences: every 8-word run holds a sentence's number, so no run repeats."""
    return " ".join(f"Rule {i}: no person shall obstruct walkway {i}." for i in range(first, last))


BYLAW = _sentences(0, 30)  # ~1,300 chars
BYLAW_SRC = {"slug": "toronto-municipal-code-743", "pinpoint": "743-41", "reproduction": "excerpt",
             "citation": {"title": "", "reference": "City of Toronto Municipal Code, c 743, § 743-41"}}


def test_excerpt_only_quote_over_the_cap_is_dropped_with_a_reason():
    from app.ask import EXCERPT_TOO_LONG
    from app.laws import EXCERPT_CHARS

    long_quote = _sentences(0, 10)
    assert len(long_quote) > EXCERPT_CHARS
    ok, dropped = verify_claims([claim(long_quote, "b1")], {"b1": BYLAW}, {"b1": BYLAW_SRC})
    assert ok == [] and dropped[0]["reason"] == EXCERPT_TOO_LONG == "excerpt-only source: quote exceeds 300 characters"
    assert dropped[0]["quote"] == f"({len(long_quote)} characters not shown: excerpt-only source)"


def test_excerpt_only_quotes_from_one_section_are_capped_in_total():
    from app.ask import EXCERPT_SECTION_FULL

    a, b, c = _sentences(0, 4), _sentences(5, 9), _sentences(10, 11)  # ~170 + ~170 + ~45 chars
    other_section = {**BYLAW_SRC, "pinpoint": "743-42"}
    ok, dropped = verify_claims([claim(a, "b1"), claim(b, "b2"), claim(c, "b1"), claim(b, "b3")],
                                {"b1": BYLAW, "b2": BYLAW, "b3": BYLAW},
                                {"b1": BYLAW_SRC, "b2": BYLAW_SRC, "b3": other_section})  # b2: same split section
    assert [x["quote"] for x in ok] == [a, c, b]  # a later quote that still fits, and another section, are kept
    assert [d["reason"] for d in dropped] == [EXCERPT_SECTION_FULL]


def test_statute_quotes_are_not_capped():
    statute = {"b1": {**BYLAW_SRC, "reproduction": "full"}}
    ok, dropped = verify_claims([claim(BYLAW, "b1"), claim(BYLAW, "b1")], {"b1": BYLAW}, statute)
    assert len(ok) == 2 and dropped == []


def test_prompt_asks_for_short_excerpt_only_quotes_and_retries_after_a_long_one():
    long = {"in_scope": True, "answer": "x", "claims": [claim(_sentences(0, 10), "b1")]}
    short = {"in_scope": True, "answer": "Owners must keep it clear.", "claims": [claim(_sentences(0, 1), "b1")]}
    llm = FakeLLM([long, short])
    result = run_ask("Who keeps sidewalks clear?", [Retrieved("b1", BYLAW, 0.1, BYLAW_SRC)], llm)
    first = " ".join(llm.prompts[0].split())
    assert "Toronto Municipal Code passages are excerpt-only" in first and "at most 300 characters" in first
    assert "too much Toronto Municipal Code text" in llm.prompts[1] and result.status == "drafted" and result.retried
    assert _sentences(0, 10) not in result.draft_markdown


def test_only_the_first_hit_of_an_excerpt_only_section_keeps_its_snippet():
    from app.ask import one_snippet_per_excerpt_section

    src = {**BYLAW_SRC, "snippet": "No person shall…"}
    full = {**src, "reproduction": "full"}
    assert [s["snippet"] for s in one_snippet_per_excerpt_section([src, src, full, full])] == [
        "No person shall…", "", "No person shall…", "No person shall…"]


def test_reproduced_chars_counts_what_the_markdown_shows():
    from app.laws import reproduced_chars

    md = f"Owners must act.\n\n> {_sentences(0, 3)}\n> — City\n\n> {_sentences(2, 5)}\n\nAlso: {_sentences(9, 10)}"
    shown = [_sentences(0, 3), _sentences(2, 5), _sentences(9, 10)]  # the overlap is shown twice, so counted twice
    assert reproduced_chars(md, BYLAW) == sum(map(len, shown)) + len(shown) - 1
    assert reproduced_chars("Owners must keep the sidewalk clear.", BYLAW) == 0
    phrase = "clear away and completely remove snow and ice from any sidewalk"
    assert reproduced_chars(f"You must {phrase}.", f"{phrase}. Also, {phrase} in front.") == len(phrase) + 1


def test_answer_prose_counts_toward_the_section_cap():
    """The answer's own sentences copying a by-law count too: the section's last quote is dropped to fit."""
    from app.ask import EXCERPT_SECTION_FULL, result_flags
    from app.review import risk_reasons

    prose = f"The by-law says: {_sentences(0, 4)}"  # ~175 chars copied in the answer itself
    quotes = [_sentences(10, 12), _sentences(20, 23)]  # ~90 + ~135: each fits, and both fit verify_claims' budget
    out = {"in_scope": True, "answer": prose, "claims": [claim(q, "b1") for q in quotes]}
    bad = {"in_scope": True, "answer": "x", "claims": [claim("made up words that are not there", "b1")]}
    llm = FakeLLM([out, bad])  # a quote was dropped: one retry for shorter quotes; it fails, so the first draft stays
    result = run_ask("Who keeps walkways clear?", [Retrieved("b1", BYLAW, 0.1, BYLAW_SRC)], llm)
    assert result.status == "drafted" and result.retried and [c["quote"] for c in result.claims] == quotes[:1]
    assert [d["reason"] for d in result.dropped] == [EXCERPT_SECTION_FULL, "quote_not_in_chunk"]
    assert "source" not in result.dropped[0] and "your own words" in llm.prompts[1]
    assert result.excerpt_overflow == [] and "excerpt_overflow" not in risk_reasons(result_flags(result))

    short = {"in_scope": True, "answer": "Owners keep walkways clear.", "claims": [claim(_sentences(20, 21), "b1")]}
    result = run_ask("Who keeps walkways clear?", [Retrieved("b1", BYLAW, 0.1, BYLAW_SRC)], FakeLLM([out, short]))
    assert result.claims[0]["quote"] == _sentences(20, 21)  # the retry's shorter quotes win

    copied = {"in_scope": True, "answer": _sentences(0, 8), "claims": [claim(_sentences(20, 21), "b1")]}
    llm = FakeLLM([copied, copied])  # prose alone over the cap: every by-law quote is dropped, then a retry
    result = run_ask("Who keeps walkways clear?", [Retrieved("b1", BYLAW, 0.1, BYLAW_SRC), hit("c1", 0.2)], llm)
    assert result.status == "unverified" and "your own words" in llm.prompts[1]


def test_prose_over_the_cap_beside_a_statute_claim_is_flagged_for_the_reviewer():
    from app.ask import result_flags
    from app.review import risk_reasons

    src = {**BYLAW_SRC, "display": "§ 743-41"}
    out = {"in_scope": True, "answer": _sentences(0, 8), "claims": [claim("a proceeding shall not be commenced")]}
    result = run_ask("q?", [Retrieved("b1", BYLAW, 0.1, src), hit("c1", 0.2)], FakeLLM([out]))
    assert result.status == "drafted" and result.excerpt_overflow == ["§ 743-41"]
    assert risk_reasons(result_flags(result))[0] == "excerpt_overflow"


# --- the excerpt cap is per section, whatever the chunk or claim pinpoint (#56 review) ---

def _split(pin):  # a chunk of section 743-41 pinpointed at its first subsection, or a claim pinned to a subsection
    return {**BYLAW_SRC, "pinpoint": pin, "section": "743-41"}


def test_quotes_from_chunks_of_one_split_section_share_the_budget():
    from app.ask import EXCERPT_SECTION_FULL

    a, b = _sentences(0, 4), _sentences(5, 9)  # ~170 + ~170
    ok, dropped = verify_claims([claim(a, "b1"), claim(b, "b2")], {"b1": BYLAW, "b2": BYLAW},
                                {"b1": _split("743-41-a"), "b2": _split("743-41-c")})
    assert [x["quote"] for x in ok] == [a] and [d["reason"] for d in dropped] == [EXCERPT_SECTION_FULL]


def test_fit_excerpts_matches_refined_claims_to_their_section():
    """pinpoint_claims narrows a claim to its subsection; fit_excerpts must still see it as the section's claim."""
    from app.ask import fit_excerpts

    hits = [Retrieved("b1", BYLAW[:600], None, _split("743-41-a")), Retrieved("b2", BYLAW[600:], None, _split("743-41-c"))]
    claims = [{**claim(_sentences(0, 4), "b1"), "source": _split("743-41-a")},
              {**claim(_sentences(20, 24), "b2"), "source": _split("743-41-c")}]
    kept, dropped, over = fit_excerpts(f"In short: {_sentences(10, 12)}", claims, hits)
    assert kept == claims[:1] and len(dropped) == 1 and over == []


def test_one_snippet_per_split_section():
    from app.ask import one_snippet_per_excerpt_section

    snippets = [s["snippet"] for s in one_snippet_per_excerpt_section(
        [{**_split("743-41-a"), "snippet": "x"}, {**_split("743-41-c"), "snippet": "y"}])]
    assert snippets == ["x", ""]


def test_a_retry_that_verifies_less_keeps_the_first_draft():
    two = {"in_scope": True, "answer": "Owners keep walkways clear.",
           "claims": [claim(_sentences(0, 10), "b1"), claim(_sentences(20, 21), "b1"), claim(_sentences(22, 23), "b1")]}
    worse = {"in_scope": True, "answer": "x", "claims": [claim(_sentences(24, 25), "b1")]}
    result = run_ask("q?", [Retrieved("b1", BYLAW, 0.1, BYLAW_SRC)], FakeLLM([two, worse]))
    assert [c["quote"] for c in result.claims] == [_sentences(20, 21), _sentences(22, 23)] and result.retried


def test_source_section_is_the_chunks_section_not_its_subsection(conn):
    from app.ask import SECTION_OF_CHUNK
    from ingest.chunks import load_sections, plan_chunks, sync_chunks
    from ingest.statutes import load_document, parse_law
    from test_statutes import LAW, row

    load_document(conn, parse_law(row(), LAW))
    doc_id = conn.execute("SELECT id FROM documents WHERE slug = 'test-act'").fetchone()[0]
    sync_chunks(conn, doc_id, plan_chunks("Test Act", load_sections(conn, doc_id)))
    rows = conn.execute(f"SELECT c.pinpoint, {SECTION_OF_CHUNK} FROM chunks c WHERE c.document_id = %s", (doc_id,)).fetchall()
    kinds = dict(conn.execute("SELECT pinpoint, kind FROM sections WHERE document_id = %s", (doc_id,)).fetchall())
    assert rows and all(kinds[section] != "subsection" for _, section in rows)


def test_failed_quotes_from_excerpt_only_chunks_are_withheld():
    long = _sentences(0, 10)
    ok, dropped = verify_claims([claim(long + " (paraphrased)", "b1"), claim(long, "zz"), claim("paraphrase of the act here", "c1")],
                                {"b1": BYLAW, "c1": CHUNKS["c1"]}, {"b1": BYLAW_SRC, "c1": {"reproduction": "full"}})
    assert [d["reason"] for d in dropped] == ["quote_not_in_chunk", "chunk_not_retrieved", "quote_not_in_chunk"]
    assert all(long not in d["quote"] for d in dropped[:2]) and dropped[2]["quote"] == "paraphrase of the act here"


def test_stored_sources_keep_one_snippet_per_excerpt_section(conn):
    """Cross-referenced chunks are appended after retrieve's dedupe: complete_draft dedupes what it stores."""
    from app.ask import complete_draft, create_pending

    src = {**BYLAW_SRC, "snippet": "No person shall…"}
    hits = [Retrieved("b1", "x", 0.1, src), Retrieved("b2", "y", None, {**src, "pinpoint": "743-41-c", "section": "743-41"})]
    aid = create_pending(conn, "q?", None, [], {}, None)
    complete_draft(conn, aid, AskResult("drafted", "d"), 1, hits)
    flags = conn.execute("SELECT flags FROM answers WHERE id = %s", (aid,)).fetchone()[0]
    assert [s["snippet"] for s in flags["sources"]] == ["No person shall…", ""]


def test_traces_get_only_an_excerpt_of_excerpt_only_passages(monkeypatch):
    """Langfuse Cloud is external: the traced prompt and claims hold no more than an excerpt of a by-law (#56)."""
    from contextlib import contextmanager

    from app import tracing

    sent = []

    class Obs:
        def update(self, **kw):
            sent.append(kw)

    @contextmanager
    def observe(name, as_type="span", **kw):
        sent.append(kw)
        yield Obs()

    monkeypatch.setattr(tracing, "observe", observe)
    long = {"in_scope": True, "answer": "Owners keep walkways clear.", "claims": [claim(_sentences(0, 10), "b1")]}
    short = {"in_scope": True, "answer": "Owners keep walkways clear.", "claims": [claim(_sentences(20, 21), "b1")]}
    llm = FakeLLM([long, short])
    run_ask("q?", [Retrieved("b1", BYLAW, 0.1, BYLAW_SRC), hit("c1", 0.2)], llm)
    assert BYLAW in llm.prompts[0]  # the model reads the whole passage
    traced = " ".join(str(v) for kw in sent for v in kw.values())
    assert _sentences(8, 12) not in traced and _sentences(0, 10) not in traced  # cut to an excerpt, long quote withheld
    assert _sentences(0, 2) in traced and CHUNKS["c1"] in traced  # the excerpt and statute text stay


def test_words_ignore_markdown_emphasis_and_dashes():
    from app.laws import reproduced_chars

    phrase = _sentences(0, 3)
    styled = phrase.replace("shall", "**shall**", 1).replace("walkway 1.", "walkway 1. —", 1)
    assert reproduced_chars(f"- *{styled}*", BYLAW) >= len(phrase) - 10
