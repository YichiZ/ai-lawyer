from app.ask import Retrieved
from app.rerank import RERANK_CANDIDATES, parse_ranking, rerank, rerank_prompt


def hit(i, text=None):
    return Retrieved(f"c{i}", text or f"passage {i} " + "word " * 300, 0.2, {"citation": {"text": f"Act, s {i}"}}, 0.0)


HITS = [hit(i) for i in range(1, 6)]


def test_prompt_lists_ids_citations_and_truncated_text():
    p = rerank_prompt("How long to sue?", HITS)
    assert "How long to sue?" in p and "[c3] Act, s 3" in p
    assert len(p.split("[c1]")[1].split("[c2]")[0].split()) < 140  # ~120 words per passage


def test_prompt_prefers_the_law_governing_the_named_jurisdiction():
    p = rerank_prompt("q", HITS)
    assert "City of Toronto Act, 2006" in p and "Municipal Act, 2001" in p


def test_parse_keeps_known_ids_dedupes_and_appends_missing():
    order = parse_ranking({"ranking": ["c3", "c9", "c3", "c1"]}, [h.chunk_id for h in HITS])
    assert order == ["c3", "c1", "c2", "c4", "c5"]


def test_parse_malformed_returns_none():
    assert parse_ranking({"nope": 1}, ["c1"]) is None
    assert parse_ranking({"ranking": "c1"}, ["c1"]) is None


def test_rerank_reorders_and_truncates():
    out, flag = rerank("q", HITS, lambda p, s: {"ranking": ["c5", "c4"]}, top_k=5)
    assert [h.chunk_id for h in out] == ["c5", "c4", "c1", "c2", "c3"] and flag is None


def test_rerank_falls_back_on_error_or_bad_output():
    def boom(p, s):
        raise RuntimeError("503")
    out, flag = rerank("q", HITS, boom, top_k=2)
    assert [h.chunk_id for h in out] == ["c1", "c2"] and flag == "rerank_error"
    out, flag = rerank("q", HITS, lambda p, s: {"bad": True}, top_k=2)
    assert [h.chunk_id for h in out] == ["c1", "c2"] and flag == "rerank_malformed"


def test_candidate_count_from_sweep():
    assert RERANK_CANDIDATES == 20  # design said 30; 20 was better and faster (Phase 3.4)


def test_retrieve_uses_reranker_on_fused_candidates(conn):
    from app.ask import retrieve
    from ingest.chunks import embed_pending, load_sections, plan_chunks, sync_chunks
    from ingest.statutes import load_document, parse_law
    from test_statutes import LAW, row

    load_document(conn, parse_law(row(), LAW))
    doc_id = conn.execute("SELECT id FROM documents WHERE slug = 'test-act'").fetchone()[0]
    sync_chunks(conn, doc_id, plan_chunks("Test Act", load_sections(conn, doc_id)))
    embed_pending(conn, lambda t: [0.01] * 1536, model="fake", workers=1)
    seen = {}

    def reverse(question, hits, top_k):
        seen["n"] = len(hits)
        return list(reversed(hits))[:top_k]

    plain = retrieve(conn, "second anniversary", [0.01] * 1536, top_k=2)
    reranked = retrieve(conn, "second anniversary", [0.01] * 1536, top_k=2, rerank=reverse)
    assert seen["n"] >= len(plain) and len(reranked) == 2
    assert [h.chunk_id for h in reranked] != [h.chunk_id for h in plain]


def test_rerank_cannot_drop_the_fused_top_hits():
    hits = [hit(i) for i in range(1, 11)]
    # the model ranks the fused #1 last: it must still be in the final top 4, in place of the lowest reranked hit
    out, _ = rerank("q", hits, lambda p, s: {"ranking": [f"c{i}" for i in range(10, 0, -1)]}, top_k=4)
    ids = [h.chunk_id for h in out]
    assert len(ids) == 4 and {"c1", "c2", "c3"} <= set(ids) and ids[0] == "c10"
