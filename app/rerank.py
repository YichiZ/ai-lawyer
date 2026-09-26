"""Listwise rerank: gemini-3.5-flash-lite orders the fused top 30 (ids + first ~120 words) in one JSON call.

Code keeps control: unknown or duplicate ids are ignored, ids the model left out keep their fused order, and any
failure falls back to the fused order (flagged) — a rerank problem never breaks retrieval.
"""
import logging
from typing import Callable

log = logging.getLogger("app.rerank")
RERANK_CANDIDATES = 30
PASSAGE_WORDS = 120
SCHEMA = {"type": "object", "properties": {"ranking": {"type": "array", "items": {"type": "string"}}},
          "required": ["ranking"]}
PROMPT = """Rank the passages by how directly they answer the research question about Ontario personal-injury law.
Return every passage id, most relevant first. Prefer the provision that states the rule asked about over
provisions that only mention the same words.

Question: {question}

Passages:
{passages}
"""


def rerank_prompt(question: str, hits: list) -> str:
    passages = "\n\n".join(
        f"[{h.chunk_id}] {h.source['citation']['text']}\n{' '.join(h.text.split()[:PASSAGE_WORDS])}" for h in hits)
    return PROMPT.format(question=question, passages=passages)


def parse_ranking(out: dict, ids: list[str]) -> list[str] | None:
    ranking = out.get("ranking") if isinstance(out, dict) else None
    if not isinstance(ranking, list):
        return None
    known, seen, order = set(ids), set(), []
    for cid in ranking:
        if isinstance(cid, str) and cid in known and cid not in seen:
            seen.add(cid)
            order.append(cid)
    return order + [cid for cid in ids if cid not in seen]


def rerank(question: str, hits: list, generate: Callable[[str, dict], dict], top_k: int) -> tuple[list, str | None]:
    """(reranked top_k hits, flag). flag is None on success, else 'rerank_error' / 'rerank_malformed'."""
    ids = [h.chunk_id for h in hits]
    try:
        order = parse_ranking(generate(rerank_prompt(question, hits), SCHEMA), ids)
    except Exception:
        log.exception("rerank failed; keeping fused order")
        return hits[:top_k], "rerank_error"
    if order is None:
        return hits[:top_k], "rerank_malformed"
    by_id = {h.chunk_id: h for h in hits}
    return [by_id[cid] for cid in order[:top_k]], None
