"""Offline sweep of fusion variants on the gold set: embeds each question once, scores every variant locally.
Exploration only — the chosen variant must then pass `scripts/eval.py retrieval` and `make eval`.

Run: uv run --env-file .env -m scripts.sweep_fusion
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg

from app.ask import TOP_K, keyword_ranking, rrf, vector_ranking
from evals.gold import load_gold
from evals.metrics import chunk_covers, mrr, recall_at_k
from ingest.vertex import batch_client, embedder

ROOT = Path(__file__).resolve().parent.parent

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
VARIANTS = {  # name: (depth, k, keyword weight, vector weight)
    "Phase 2 (50, k60, 1:1)": (50, 60, 1.0, 1.0),
    "3.3 chosen (k10, 0.3:1)": (50, 10, 0.3, 1.0),
    "vector only": (50, 60, 0.0, 1.0),
}


def main() -> int:
    gold = [g for g in load_gold() if not g["must_refuse"]]
    embed = embedder(batch_client(), "RETRIEVAL_QUERY")
    with ThreadPoolExecutor(4) as pool:
        vectors = list(pool.map(lambda g: embed(g["question"]), gold))
    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute("SELECT c.id, d.slug, c.pinpoint FROM chunks c JOIN documents d ON d.id = c.document_id").fetchall()
        covers = chunk_covers(conn, [r[0] for r in rows])
        hit = {cid: (slug, pin, covers[cid]) for cid, slug, pin in rows}
        vec_lists = [vector_ranking(conn, v, 100) for v in vectors]
        print(f"{'variant':<30} recall@8   mrr   misses")
        for name, (depth, k, wk, wv) in VARIANTS.items():
            rec, rr, missed = [], [], []
            for g, vec in zip(gold, vec_lists):
                kw = keyword_ranking(conn, g["question"], depth) if wk else []
                fused = [int(c[1:]) for c, _ in rrf([[f"c{c}" for c in kw], [f"c{c}" for c, _ in vec[:depth]]], k, [wk, wv])][:TOP_K]
                ranked = [hit[c] for c in fused]
                rec.append(recall_at_k(ranked, g["expected"], TOP_K)); rr.append(mrr(ranked, g["expected"]))
                if not rec[-1]:
                    missed.append(g["id"])
            print(f"{name:<30} {sum(rec) / len(rec):.3f}   {sum(rr) / len(rr):.3f}  {' '.join(missed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
