from app.ask import Retrieved
from app.rerank import RERANK_CANDIDATES, parse_ranking, rerank, rerank_prompt


def hit(i, text=None):
    return Retrieved(f"c{i}", text or f"passage {i} " + "word " * 300, 0.2, {"citation": {"text": f"Act, s {i}"}}, 0.0)


HITS = [hit(i) for i in range(1, 6)]


def test_prompt_lists_ids_citations_and_truncated_text():
    p = rerank_prompt("How long to sue?", HITS)
    assert "How long to sue?" in p and "[c3] Act, s 3" in p
    assert len(p.split("[c1]")[1].split("[c2]")[0].split()) < 140  # ~120 words per passage


def test_parse_keeps_known_ids_dedupes_and_appends_missing():
    order = parse_ranking({"ranking": ["c3", "c9", "c3", "c1"]}, [h.chunk_id for h in HITS])
    assert order == ["c3", "c1", "c2", "c4", "c5"]


def test_parse_malformed_returns_none():
    assert parse_ranking({"nope": 1}, ["c1"]) is None
    assert parse_ranking({"ranking": "c1"}, ["c1"]) is None


def test_rerank_reorders_and_truncates():
    out, flag = rerank("q", HITS, lambda p, s: {"ranking": ["c5", "c4"]}, top_k=3)
    assert [h.chunk_id for h in out] == ["c5", "c4", "c1"] and flag is None


def test_rerank_falls_back_on_error_or_bad_output():
    def boom(p, s):
        raise RuntimeError("503")
    out, flag = rerank("q", HITS, boom, top_k=2)
    assert [h.chunk_id for h in out] == ["c1", "c2"] and flag == "rerank_error"
    out, flag = rerank("q", HITS, lambda p, s: {"bad": True}, top_k=2)
    assert [h.chunk_id for h in out] == ["c1", "c2"] and flag == "rerank_malformed"


def test_candidate_count_matches_design():
    assert RERANK_CANDIDATES == 30
