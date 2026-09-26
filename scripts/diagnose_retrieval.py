"""For gold items that retrieval misses: where do the expected pinpoints rank in keyword, vector and fused lists?

Run: uv run --env-file .env scripts/diagnose_retrieval.py [id ...]   (default: misses in the latest retrieval run)
"""
import glob
import json
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.ask import CANDIDATES, TOP_K, keyword_ranking, rrf, vector_ranking  # noqa: E402
from evals.gold import load_gold  # noqa: E402
from evals.metrics import chunk_covers, matches  # noqa: E402
from ingest.vertex import embedder, make_client  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
DEPTH = 200


def rank_of(ids: list[int], pins: dict[int, tuple[str, str]], expected: list[dict]) -> str:
    r = next((i for i, cid in enumerate(ids, 1) if matches(pins[cid], expected)), None)
    return "—" if r is None else str(r)


def main() -> int:
    gold = {g["id"]: g for g in load_gold()}
    ids = sys.argv[1:] or [x["id"] for x in json.load(open(sorted(glob.glob(str(ROOT / "evals/runs/*-retrieval.json")))[-1]))["items"]
                           if x["recall@8"] == 0]
    embed = embedder(make_client(), "RETRIEVAL_QUERY")
    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute("SELECT c.id, d.slug, c.pinpoint FROM chunks c JOIN documents d ON d.id = c.document_id").fetchall()
        covers = chunk_covers(conn, [r[0] for r in rows])
        pins = {cid: (slug, pin, covers[cid]) for cid, slug, pin in rows}
        terms_of = lambda q: conn.execute("SELECT plainto_tsquery('english', %s)::text", (q,)).fetchone()[0]
        print(f"{'id':<9} {'keyword':>8} {'vector':>7} {'fused':>6}  expected / top vector hit / query terms")
        for gid in ids:
            g = gold[gid]
            kw = keyword_ranking(conn, g["question"], DEPTH)
            vec = vector_ranking(conn, embed(g["question"]), DEPTH)
            vec_ids = [cid for cid, _ in vec]
            fused = [int(c[1:]) for c, _ in rrf([[f"c{c}" for c in kw[:CANDIDATES]], [f"c{c}" for c in vec_ids[:CANDIDATES]]])]
            exp = ", ".join(f"{e['slug']} {e['pinpoint']}" for e in g["expected"])
            print(f"{gid:<9} {rank_of(kw, pins, g['expected']):>8} {rank_of(vec_ids, pins, g['expected']):>7} "
                  f"{rank_of(fused, pins, g['expected']):>6}  {exp}\n{'':<34}top vector: {pins[vec_ids[0]][:2]}  terms: {terms_of(g['question'])}")
    print(f"(ranks within top {DEPTH}; fused uses top {CANDIDATES} of each, kept top {TOP_K})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
