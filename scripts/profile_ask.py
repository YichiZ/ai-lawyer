"""Stage-by-stage latency of the /ask pipeline, run sequentially (no eval concurrency): embed, retrieve, rerank,
generate (per attempt), total. Run: uv run --env-file .env scripts/profile_ask.py [n]"""
import os
import statistics
import sys
import time
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ask import pinpoint_claims, retrieve, run_ask  # noqa: E402
from app.rerank import make_reranker  # noqa: E402
from evals.gold import load_gold  # noqa: E402
from ingest.vertex import CHEAP_MODEL, embedder, json_generator, make_client  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")


def timed(fn, bucket):
    def run(*a, **kw):
        t = time.perf_counter()
        try:
            return fn(*a, **kw)
        finally:
            bucket.append((time.perf_counter() - t) * 1000)
    return run


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    gold = [g for g in load_gold() if not g["must_refuse"]][:n]
    client = make_client()
    t = {k: [] for k in ("embed", "retrieve+rerank", "rerank", "generate", "attempts", "total", "sources")}
    sizes, failures = [], []
    embed = timed(embedder(client, "RETRIEVAL_QUERY"), t["embed"])
    rerank = timed(make_reranker(json_generator(client, model=CHEAP_MODEL)), t["rerank"])
    raw_generate = json_generator(client)

    def sized(prompt, schema):
        sizes.append(len(prompt))
        return raw_generate(prompt, schema)

    generate = timed(sized, t["generate"])
    with psycopg.connect(DATABASE_URL) as conn:
        for g in gold:
            t0 = time.perf_counter()
            vec = embed(g["question"])
            t1 = time.perf_counter()
            hits = retrieve(conn, g["question"], vec, rerank=rerank)
            t["retrieve+rerank"].append((time.perf_counter() - t1) * 1000)
            t["sources"].append((time.perf_counter() - t0) * 1000)
            before = len(t["generate"])
            try:
                run_ask(g["question"], hits, generate, refine=lambda c: pinpoint_claims(conn, c))
            except Exception as e:  # record, keep profiling
                failures.append((g["id"], type(e).__name__, str(e)[:60]))
            t["attempts"].append(len(t["generate"]) - before)
            t["total"].append((time.perf_counter() - t0) * 1000)
    print(f"  prompt chars: median {statistics.median(sizes):.0f}, max {max(sizes)}; failures: {failures}")
    slow = sorted(zip(t["generate"], sizes), reverse=True)[:5]
    print("  slowest generate calls (ms, prompt chars):", [(round(a), b) for a, b in slow])
    for k, v in t.items():
        if k == "attempts":
            print(f"  generate attempts: {sum(v)} over {len(v)} questions ({sum(x > 1 for x in v)} needed a retry)")
            continue
        q = statistics.quantiles(v, n=20)
        print(f"  {k:<16} p50 {statistics.median(v):7.0f} ms   p95 {q[18]:7.0f} ms   max {max(v):7.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
