"""Offline check of the listwise reranker on the gold set: fused top 30 -> Flash-Lite rerank -> top 8.
Reports recall@8 / MRR with and without rerank, rerank latency and flags. Exploration only.

Run: uv run --env-file .env -m scripts.sweep_rerank [candidates]
"""
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg

from app.ask import TOP_K, retrieve
from app.rerank import RERANK_CANDIDATES, rerank
from evals.gold import load_gold
from evals.metrics import chunk_covers, mrr, recall_at_k
from ingest.vertex import CHEAP_MODEL, batch_client, embedder, json_generator

ROOT = Path(__file__).resolve().parent.parent

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")


def main() -> int:
    candidates = int(sys.argv[1]) if len(sys.argv) > 1 else RERANK_CANDIDATES
    gold = [g for g in load_gold() if not g["must_refuse"]]
    client = batch_client()
    embed, cheap = embedder(client, "RETRIEVAL_QUERY"), json_generator(client, model=CHEAP_MODEL)

    def one(g):
        with psycopg.connect(DATABASE_URL) as conn:
            hits = retrieve(conn, g["question"], embed(g["question"]), top_k=candidates)
            t = time.perf_counter()
            reranked, flag = rerank(g["question"], hits, cheap, TOP_K)
            ms = (time.perf_counter() - t) * 1000
            covers = chunk_covers(conn, [int(h.chunk_id[1:]) for h in hits])
        as_hits = lambda hs: [(h.source["slug"], h.source["pinpoint"], covers[int(h.chunk_id[1:])]) for h in hs]
        return g, as_hits(hits[:TOP_K]), as_hits(reranked), ms, flag

    with ThreadPoolExecutor(2) as pool:
        rows = list(pool.map(one, gold))
    for name, idx in (("fused (3.3)", 1), ("fused + rerank", 2)):
        rec = [recall_at_k(r[idx], r[0]["expected"], TOP_K) for r in rows]
        rr = [mrr(r[idx], r[0]["expected"]) for r in rows]
        missed = [r[0]["id"] for r, x in zip(rows, rec) if not x]
        print(f"{name:<16} recall@8 {sum(rec) / len(rec):.3f}  mrr {sum(rr) / len(rr):.3f}  misses {' '.join(missed)}")
    ms = [r[3] for r in rows]
    q = statistics.quantiles(ms, n=100)
    print(f"rerank latency p50 {q[49]:.0f} ms, p95 {q[94]:.0f} ms; flags: {[r[4] for r in rows if r[4]]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
