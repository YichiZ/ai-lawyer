"""Run Langfuse experiments on the gold set.

Run: uv run --env-file .env scripts/eval.py retrieval
Needs LANGFUSE_* keys (Langfuse Cloud) and Vertex ADC. Each run is also saved to evals/runs/ (gitignored).
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from langfuse import Evaluation, Langfuse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.ask import retrieve  # noqa: E402
from evals.gold import load_gold  # noqa: E402
from evals.langfuse_io import DATASET, upsert_dataset  # noqa: E402
from evals.metrics import mrr, recall_at_k, summarize  # noqa: E402
from ingest.vertex import embedder, make_client  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
RUNS = ROOT / "evals" / "runs"
K = 8
CONCURRENCY = 4


def retrieval_task(embed):
    def task(*, item, **_):
        question = item.input["question"]
        t0 = time.perf_counter()
        with psycopg.connect(DATABASE_URL) as conn:
            hits = retrieve(conn, question, embed(question))
        return {
            "ranked": [[h.source["slug"], h.source["pinpoint"]] for h in hits],
            "citations": [h.source["citation"]["text"] for h in hits],
            "best_distance": min((h.distance for h in hits if h.distance is not None), default=None),
            "latency_ms": round((time.perf_counter() - t0) * 1000),
        }
    return task


def retrieval_evaluator(*, output, expected_output, **_):
    if expected_output["must_refuse"]:
        return []
    ranked = [tuple(h) for h in output["ranked"]]
    return [Evaluation(name=f"recall@{K}", value=recall_at_k(ranked, expected_output["expected"], K)),
            Evaluation(name="mrr", value=mrr(ranked, expected_output["expected"]))]


def run_retrieval(lf: Langfuse) -> dict:
    gold = {g["id"]: g for g in load_gold()}
    upsert_dataset(lf, list(gold.values()))
    dataset = lf.get_dataset(DATASET)
    items = [i for i in dataset.items if i.id in gold]  # only items still in gold.jsonl
    result = lf.run_experiment(
        name="retrieval", description=f"Hybrid retrieval (keyword + vector, RRF) top {K} vs gold pinpoints",
        data=items, task=retrieval_task(embedder(make_client(), "RETRIEVAL_QUERY")),
        evaluators=[retrieval_evaluator], max_concurrency=CONCURRENCY,
        metadata={"k": K, "gold_items": len(items)},
    )
    rows, oos = [], []
    for r in result.item_results:
        g = gold[r.item.id]
        scores = {e.name: e.value for e in r.evaluations}
        row = {"id": g["id"], "topic": g["topic"], "question": g["question"], **r.output, **scores}
        (oos if g["must_refuse"] else rows).append(row)
    summary = summarize(rows, [f"recall@{K}", "mrr"])
    return {"experiment": "retrieval", "run_name": result.run_name, "url": result.dataset_run_url,
            "summary": summary, "items": rows, "out_of_scope": oos}


def main() -> int:
    kind = sys.argv[1] if len(sys.argv) > 1 else "retrieval"
    lf = Langfuse()
    if not lf.auth_check():
        sys.exit("Langfuse auth failed: check LANGFUSE_* in .env (run with uv run --env-file .env)")
    report = {"retrieval": run_retrieval}[kind](lf)
    lf.flush()
    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RUNS / f"{stamp}-{kind}.json"
    path.write_text(json.dumps(report, indent=2, default=str))
    print(f"{kind}: {report['url'] or report['run_name']}\nsaved {path.relative_to(ROOT)}")
    for group, s in sorted(report["summary"].items(), key=lambda kv: (kv[0] != "all", kv[0])):
        print(f"  {group:<20} n={s['n']:<3} " + "  ".join(f"{m} {v:.3f}" for m, v in s.items() if m != "n"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
