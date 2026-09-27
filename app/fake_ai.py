"""Deterministic stand-in for Vertex, used only by end-to-end UI tests (AI_FAKE=1). Never used for evals.

embed_query returns the stored embedding of the best keyword match, so retrieval and the grounding gate run for real;
generate quotes the first sentence of the first passage, so quote verification runs for real.
"""
import re
from typing import Callable, ContextManager

import psycopg
from pgvector.psycopg import register_vector

PASSAGE = re.compile(r"^\[(c\d+)\][^\n]*\n([^\n]+)", re.M)


class FakeAI:
    def __init__(self, connect: Callable[[], ContextManager[psycopg.Connection]]):
        self.connect = connect

    def embed_query(self, text: str) -> list[float]:
        with self.connect() as conn:
            return self._embed(conn, text)

    def _embed(self, conn: psycopg.Connection, text: str) -> list[float]:
        register_vector(conn)
        row = conn.execute(
            "WITH t AS (SELECT replace(plainto_tsquery('english', %s)::text, '&', '|')::tsquery AS q)"
            " SELECT embedding FROM chunks c, t WHERE c.embedding IS NOT NULL AND c.tsv @@ t.q"
            " ORDER BY ts_rank_cd(c.tsv, t.q) DESC, c.id LIMIT 1",
            (text,),
        ).fetchone()
        return [float(x) for x in row[0].to_list()] if row else [1.0] + [0.0] * 1535

    def generate(self, prompt: str, schema: dict) -> dict:
        m = PASSAGE.search(prompt.split("Passages:", 1)[1])
        if not m:
            return {"in_scope": True, "answer": "The passages do not answer this.", "claims": []}
        chunk_id, first_line = m.groups()
        quote = re.split(r"(?<=[.;:])\s", first_line, maxsplit=1)[0]
        return {"in_scope": True, "answer": f"[Test answer] The first passage says: {quote}",
                "claims": [{"text": "Test claim.", "chunk_id": chunk_id, "quote": quote}]}

    def rerank(self, question: str, hits: list, top_k: int) -> list:
        """Reverse the fused order (keeping the fused top 3, like the real reranker), so the UI's reorder is visible."""
        from app.rerank import rerank

        return rerank(question, hits, lambda prompt, schema: {"ranking": [h.chunk_id for h in reversed(hits)]}, top_k)[0]

    def search_web(self, question: str) -> tuple[str, list[dict]]:
        return ("[Test web answer] Official pages describe this rule.",
                [{"url": "https://www.ontario.ca/page/test", "title": "Test page", "domain": "ontario.ca"}])
