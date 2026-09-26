"""Run Langfuse experiments on the gold set.

Run: uv run --env-file .env scripts/eval.py retrieval | answers | gate | record [--from-latest]
  gate    run both experiments and compare with evals/baseline.json (exit 1 on regression) — `make eval`
  record  run both and write evals/baseline.json; --from-latest uses the newest saved runs instead
Needs LANGFUSE_* keys (Langfuse Cloud) and Vertex ADC. Each run is also saved to evals/runs/ (gitignored).
"""
import json
import os
import random
import sys
import time
from statistics import mean, quantiles
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from langfuse import Evaluation, Langfuse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.ask import GATE_MAX_DISTANCE, pinpoint_claims, retrieve, run_ask  # noqa: E402
from evals.answers import JUDGE_MODEL, facts_covered, gate_tradeoff, judge_answer, refusal_correct, verified_rate  # noqa: E402
from evals.baseline import BASELINE_PATH, compare, corpus_hash, flatten, gold_hash  # noqa: E402
from evals.gold import GOLD_PATH, load_gold  # noqa: E402
from evals.langfuse_io import DATASET, upsert_dataset  # noqa: E402
from evals.metrics import chunk_covers, mrr, recall_at_k, summarize  # noqa: E402
from app.rerank import RERANK_CANDIDATES, make_reranker  # noqa: E402
from ingest.vertex import ANSWER_MODEL, CHEAP_MODEL, embedder, json_generator, make_client  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
RUNS = ROOT / "evals" / "runs"
K = 8
CONCURRENCY = 2  # 4 hit Vertex per-minute quota (429) on the answers run


def eval_client():
    return make_client(attempts=8, initial_delay=2.0, max_delay=60.0, timeout_ms=60_000)  # 30 s timed out on long answers


def require_complete(result, items, kind: str) -> None:
    """A run with missing items must not be scored or recorded."""
    done = {r.item.id for r in result.item_results if r.output is not None}
    missing = sorted(i.id for i in items if i.id not in done)
    if missing:
        raise SystemExit(f"{kind}: {len(missing)} item(s) failed after retries: {missing} — rerun")


def _retrievers(client):
    """Same retrieval as /ask: query embedding + Flash-Lite rerank."""
    return embedder(client, "RETRIEVAL_QUERY"), make_reranker(json_generator(client, model=CHEAP_MODEL))


def retrieval_task(embed, rerank=None):
    def task(*, item, **_):
        question = item.input["question"]
        t0 = time.perf_counter()
        with psycopg.connect(DATABASE_URL) as conn:
            hits = retrieve(conn, question, embed(question), rerank=rerank)
            covers = chunk_covers(conn, [int(h.chunk_id[1:]) for h in hits])
        return {
            "ranked": [[h.source["slug"], h.source["pinpoint"], covers[int(h.chunk_id[1:])]] for h in hits],
            "citations": [h.source["citation"]["text"] for h in hits],
            "best_distance": min((h.distance for h in hits if h.distance is not None), default=None),
            "latency_ms": round((time.perf_counter() - t0) * 1000),
        }
    return task


def retrieval_evaluator(*, output, expected_output, **_):
    if expected_output["must_refuse"]:
        return []
    ranked = [tuple(h) for h in output["ranked"]]  # (slug, label pinpoint, covered pinpoints)
    return [Evaluation(name=f"recall@{K}", value=recall_at_k(ranked, expected_output["expected"], K)),
            Evaluation(name="mrr", value=mrr(ranked, expected_output["expected"]))]


def run_retrieval(lf: Langfuse) -> dict:
    gold = {g["id"]: g for g in load_gold()}
    upsert_dataset(lf, list(gold.values()))
    dataset = lf.get_dataset(DATASET)
    items = [i for i in dataset.items if i.id in gold]  # only items still in gold.jsonl
    result = lf.run_experiment(
        name="retrieval", description=f"Hybrid retrieval (keyword + vector, RRF) top {K} vs gold pinpoints",
        data=items, task=retrieval_task(*_retrievers(eval_client())),
        evaluators=[retrieval_evaluator], max_concurrency=CONCURRENCY,
        metadata={"k": K, "gold_items": len(items), "rerank_candidates": RERANK_CANDIDATES},
    )
    require_complete(result, items, "retrieval")
    rows, oos = [], []
    for r in result.item_results:
        g = gold[r.item.id]
        scores = {e.name: e.value for e in r.evaluations}
        row = {"id": g["id"], "topic": g["topic"], "question": g["question"], **r.output, **scores}
        (oos if g["must_refuse"] else rows).append(row)
    summary = summarize(rows, [f"recall@{K}", "mrr"])
    return {"experiment": "retrieval", "run_name": result.run_name, "url": result.dataset_run_url,
            "summary": summary, "items": rows, "out_of_scope": oos}


def answer_task(embed, rerank, generate):
    def task(*, item, **_):
        question = item.input["question"]
        t0 = time.perf_counter()
        with psycopg.connect(DATABASE_URL) as conn:
            hits = retrieve(conn, question, embed(question), rerank=rerank)
            t_sources = time.perf_counter()
            result = run_ask(question, hits, generate, refine=lambda claims: pinpoint_claims(conn, claims))
        return {
            "status": result.status,
            "draft": result.draft_markdown,
            "claims": [{"text": c["text"], "quote": c["quote"], "citation": c["source"]["citation"]["text"]}
                       for c in result.claims],
            "kept": len(result.claims), "dropped": len(result.dropped), "retried": result.retried,
            "best_distance": min((h.distance for h in hits if h.distance is not None), default=None),
            "sources_ms": round((t_sources - t0) * 1000), "total_ms": round((time.perf_counter() - t0) * 1000),
        }
    return task


def answer_evaluator(judge):
    def evaluate(*, output, expected_output, **_):
        scores = {
            "refusal_correct": float(refusal_correct(output["status"], expected_output["must_refuse"])),
            "has_verified_claim": float(output["kept"] > 0),
            "verified_claim_rate": verified_rate(output["kept"], output["dropped"]),
            "facts_covered": facts_covered(output["draft"], expected_output["facts"]),
        }
        if not expected_output["must_refuse"]:
            verdict = judge_answer(output["draft"], output["claims"], judge)
            output["judge"] = verdict  # kept in the local report for the spot check
            scores |= {k: verdict[k] for k in ("citation_supported", "faithful", "no_advice")}
            if verdict["error"]:
                scores["judge_error"] = 1.0
        return [Evaluation(name=k, value=v, metadata={"judge_model": JUDGE_MODEL} if k in
                           ("citation_supported", "faithful", "no_advice") else None)
                for k, v in scores.items() if v is not None]
    return evaluate


def _mean(rows: list[dict], key: str) -> float | None:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(mean(vals), 3) if vals else None


def run_answers(lf: Langfuse) -> dict:
    gold = {g["id"]: g for g in load_gold()}
    upsert_dataset(lf, list(gold.values()))
    items = [i for i in lf.get_dataset(DATASET).items if i.id in gold]
    client = eval_client()
    result = lf.run_experiment(
        name="answers", description="Full /ask pipeline (no DB writes) + code metrics + LLM judge",
        data=items, task=answer_task(*_retrievers(client), json_generator(client)),
        evaluators=[answer_evaluator(json_generator(client, model=JUDGE_MODEL))], max_concurrency=CONCURRENCY,
        metadata={"answer_model": ANSWER_MODEL, "judge_model": JUDGE_MODEL, "gate_max_distance": GATE_MAX_DISTANCE},
    )
    require_complete(result, items, "answers")
    rows = []
    for r in result.item_results:
        g = gold[r.item.id]
        rows.append({"id": g["id"], "topic": g["topic"], "question": g["question"], "must_refuse": g["must_refuse"],
                     **r.output, **{e.name: e.value for e in r.evaluations}})
    ins, oos = [r for r in rows if not r["must_refuse"]], [r for r in rows if r["must_refuse"]]
    metrics = ["has_verified_claim", "verified_claim_rate", "facts_covered", "citation_supported", "faithful",
               "no_advice", "refusal_correct"]
    summary = {"in_scope": {"n": len(ins), **{m: _mean(ins, m) for m in metrics}},
               "out_of_scope": {"n": len(oos), "refusal_correct": _mean(oos, "refusal_correct")},
               "judge_errors": sum(1 for r in ins if r.get("judge_error")),
               "latency_ms": {k: {"p50": quantiles([r[k] for r in rows], n=100)[49],
                                  "p95": quantiles([r[k] for r in rows], n=100)[94]} for k in ("sources_ms", "total_ms")}}
    for topic in sorted({r["topic"] for r in ins}):
        t = [r for r in ins if r["topic"] == topic]
        summary[topic] = {"n": len(t), **{m: _mean(t, m) for m in ("has_verified_claim", "facts_covered", "citation_supported")}}
    gate = gate_tradeoff([r["best_distance"] for r in ins], [r["best_distance"] for r in oos],
                         [0.22, 0.24, 0.26, 0.28, 0.30, 0.35])
    judged = [(r["id"], c, v) for r in ins if r.get("judge") and not r["judge"]["error"]
              for c, v in zip(r["claims"], r["judge"]["reasons"])]
    spot = [{"id": i, "claim": c["text"], "quote": c["quote"], "citation": c["citation"],
             "judge_supported": v.get("supported"), "judge_reason": v.get("reason")}
            for i, c, v in random.Random(2026).sample(judged, min(10, len(judged)))]
    return {"experiment": "answers", "run_name": result.run_name, "url": result.dataset_run_url,
            "summary": summary, "gate_tradeoff": gate, "judge_spot_check": spot, "items": rows}


def combined(retrieval: dict, answers: dict) -> dict:
    with psycopg.connect(DATABASE_URL) as conn:
        corpus = corpus_hash(conn)
    return {"recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "corpus_hash": corpus, "gold_hash": gold_hash(GOLD_PATH),
            "models": {"answer": ANSWER_MODEL, "judge": JUDGE_MODEL, "embedding": "gemini-embedding-2"},
            "gate_max_distance": GATE_MAX_DISTANCE,
            "runs": {"retrieval": retrieval["url"], "answers": answers["url"]},
            "latency_ms": answers["summary"]["latency_ms"],
            "metrics": {k: round(v, 4) for k, v in flatten(retrieval, answers).items()}}


def latest(kind: str) -> dict:
    return json.loads(sorted(RUNS.glob(f"*-{kind}.json"))[-1].read_text())


def save(kind: str, report: dict) -> Path:
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{kind}.json"
    path.write_text(json.dumps(report, indent=2, default=str))
    return path


def gate_or_record(lf: Langfuse | None, mode: str, from_latest: bool) -> int:
    if from_latest:
        retrieval, answers = latest("retrieval"), latest("answers")
    else:
        retrieval, answers = run_retrieval(lf), run_answers(lf)
        save("retrieval", retrieval), save("answers", answers)
        lf.flush()
    current = combined(retrieval, answers)
    if mode == "record":
        BASELINE_PATH.write_text(json.dumps(current, indent=2) + "\n")
        print(f"recorded {BASELINE_PATH.relative_to(ROOT)}")
        for k, v in current["metrics"].items():
            print(f"  {k:<42} {v:.3f}")
        return 0
    ok, lines = compare(current, json.loads(BASELINE_PATH.read_text()))
    print("\n".join(lines))
    return 0 if ok else 1


def main() -> int:
    kind = sys.argv[1] if len(sys.argv) > 1 else "retrieval"
    from_latest = "--from-latest" in sys.argv
    if kind in ("gate", "record"):
        return gate_or_record(None if from_latest else Langfuse(), kind, from_latest)
    lf = Langfuse()
    if not lf.auth_check():
        sys.exit("Langfuse auth failed: check LANGFUSE_* in .env (run with uv run --env-file .env)")
    report = {"retrieval": run_retrieval, "answers": run_answers}[kind](lf)
    lf.flush()
    path = save(kind, report)
    print(f"{kind}: {report['url'] or report['run_name']}\nsaved {path.relative_to(ROOT)}")
    for group, s in report["summary"].items():
        if isinstance(s, dict) and "n" in s:
            print(f"  {group:<20} n={s['n']:<3} " + "  ".join(f"{m} {v}" for m, v in s.items() if m != "n"))
        else:
            print(f"  {group:<20} {s}")
    for row in report.get("gate_tradeoff", []):
        print(f"  gate {row['threshold']:.2f}: refuses {row['oos_refused']} out-of-scope, {row['in_scope_refused']} in-scope")
    return 0


if __name__ == "__main__":
    sys.exit(main())
