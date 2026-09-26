import pytest

from app.ask import (
    GATE_MAX_DISTANCE,
    Retrieved,
    compose_draft,
    normalize,
    rrf,
    run_ask,
    verify_claims,
)


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
    sources = {"c1": {"citation": {"title": "Limitations Act, 2002", "reference": "SO 2002, c 24, Sched B, s 4"}}}
    md = compose_draft("You generally have two years.", [claim("a proceeding shall not be commenced")], sources)
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
