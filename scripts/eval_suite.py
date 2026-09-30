"""Production eval suite (docs/archive/evals-plan.md): pinpoint, search, safety, abstention, robustness, glossary.

Run: uv run --env-file .env -m scripts.eval_suite [pinpoint|search|safety|abstention|robustness|glossary ...]
(no names = all). Uses Vertex (ADC); results saved to evals/runs/<ts>-suite-<name>.json; exit 1 if a threshold is missed.
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from app.ask import library_titles, pinpoint_claims, result_flags, retrieve, retrieve_for_answer, run_ask
from app.rerank import make_reranker
from app.review import risk_reasons
from app.search import group_by_law, search_hits, suggest
from evals.answers import JUDGE_MODEL, judge_answer
from evals.gold import load_gold
from evals.metrics import chunk_covers, recall_at_k
from app.authorities import unsourced_authorities
from evals.suite import (THRESHOLDS, abstention_acceptable, abstention_outcome, advice_phrases, cited_names,
                         injection_resisted,
                         is_non_answer, jaccard, judge_definition, passed, rate, score_hit, score_jump, score_pinpoint,
                         secondary_labelled)
from ingest.glossary_build import judged_sources
from ingest.vertex import CHEAP_MODEL, batch_client, embedder, json_generator

ROOT = Path(__file__).resolve().parent.parent

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
DATA = ROOT / "evals" / "data"
RUNS = ROOT / "evals" / "runs"
CONCURRENCY = 2  # gemini-3.7-flash 429s above this (see Lessons learned)
K = 8


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (DATA / name).read_text().splitlines() if line.strip()]


class Models:
    def __init__(self):
        client = batch_client()
        self.embed = embedder(client, "RETRIEVAL_QUERY")
        self.rerank = make_reranker(json_generator(client, model=CHEAP_MODEL))
        self.generate = json_generator(client)
        self.judge = json_generator(client, model=JUDGE_MODEL)


def pmap(fn, items: list, failed: list, workers: int = CONCURRENCY) -> list[tuple]:
    """[(item, fn(item))] for the items that succeeded; a failing item goes to `failed` with its error (#83),
    so one exception doesn't lose the run. A run with failed items is reported as failed (see main)."""
    def safe(item):
        try:
            return item, fn(item)
        except Exception as e:  # recorded, not swallowed: main fails the eval and prints the count
            failed.append({"item": item, "error": repr(e)})
            return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [r for r in pool.map(safe, items) if r is not None]


def answer(m: Models, question: str) -> dict:
    """The /ask draft pipeline, exactly as the background drafter runs it."""
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        hits = retrieve_for_answer(conn, question, m.embed(question), rerank=m.rerank)
        result = run_ask(question, hits, m.generate, refine=lambda claims: pinpoint_claims(conn, claims),
                         library_titles=library_titles(conn))
    claims = [{"text": c["text"], "quote": c["quote"], "slug": c["source"]["slug"],
               "pinpoint": c["source"]["pinpoint"], "title": c["source"]["title"], "kind": c["source"].get("kind"),
               "citation": c["source"]["citation"]["text"]} for c in result.claims]
    flags = result_flags(result)  # the flags complete_draft stores, so risk is computed as in production
    return {"status": result.status, "draft": result.draft_markdown, "claims": claims, "dropped": len(result.dropped),
            "flags": flags, "risk": risk_reasons(flags)}


# 1 --------------------------------------------------------------------------------------------------------------

def run_pinpoint(m: Models) -> dict:
    gold = [g for g in load_gold() if not g.get("must_refuse")]
    failed = []
    done = pmap(lambda g: answer(m, g["question"]), gold, failed)
    outputs = [out for _, out in done]
    rows = []
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        for g, out in done:
            for c in out["claims"]:
                row = conn.execute(
                    "SELECT s.id, s.text FROM sections s JOIN documents d ON d.id = s.document_id"
                    " WHERE d.slug = %s AND s.pinpoint = %s", (c["slug"], c["pinpoint"])).fetchone()
                narrower = [t for (t,) in conn.execute("SELECT text FROM sections WHERE parent_id = %s",
                                                       (row[0],)).fetchall()] if row else []
                rows.append({"id": g["id"], "citation": c["citation"], "quote": c["quote"],
                             **score_pinpoint(c["quote"], row[1] if row else None, narrower)})
    metrics = {"claims": len(rows), "precision": rate([r["correct"] for r in rows]),
               "precise_rate": rate([r["precise"] for r in rows]),
               "answers_with_claims": sum(bool(o["claims"]) for o in outputs), "answers": len(outputs)}
    return {"metrics": metrics, "items": rows, "failed": failed}


# 2 --------------------------------------------------------------------------------------------------------------

def run_search(m: Models) -> dict:
    items, failed = load("search.jsonl"), []
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        def work(it):
            if it["kind"] == "jump":
                got = suggest(conn, it["query"])
                return {**it, "got": got[0]["url"] if got else None, "ok": score_jump(got, it["expected_url"])}
            groups = group_by_law(search_hits(conn, it["query"], m.embed(it["query"]), rerank=m.rerank))
            return {**it, "got": [g["slug"] for g in groups[:3]], "ok": score_hit(groups, it["expected_slug"])}
        rows = [row for _, row in pmap(work, items, failed, workers=1)]  # one worker: the connection is shared
    metrics = {"jump_accuracy": rate([r["ok"] for r in rows if r["kind"] == "jump"]),
               "hit@3": rate([r["ok"] for r in rows if r["kind"] == "hit"]), "n": len(rows)}
    return {"metrics": metrics, "items": rows, "failed": failed}


# 3 --------------------------------------------------------------------------------------------------------------

def run_safety(m: Models) -> dict:
    items = load("safety.jsonl")
    failed = []

    def work(it):
        out = answer(m, it["question"])
        verdict = judge_answer(out["draft"], [{"text": c["text"], "quote": c["quote"], "citation": c["citation"]}
                                              for c in out["claims"]], m.judge) if out["status"] == "drafted" else None
        return out, verdict
    rows = []
    for it, (out, verdict) in pmap(work, items, failed):
        phrases = advice_phrases(out["draft"])
        judge_advice = bool(verdict and verdict.get("no_advice") == 0.0)
        rows.append({**it, "status": out["status"], "draft": out["draft"], "advice_phrases": phrases,
                     "judge_advice": judge_advice, "no_advice": not phrases and not judge_advice,
                     "injection_resisted": injection_resisted(out["draft"], it["canary"]),
                     "refused": out["status"] in ("not_found", "out_of_scope"), "flagged": bool(out["risk"]),
                     "risk": out["risk"]})
    by = lambda cat: [r for r in rows if r["category"] == cat]  # noqa: E731
    metrics = {
        "no_advice": rate([r["no_advice"] for r in rows]),
        "injection_resisted": rate([r["injection_resisted"] and r["no_advice"] for r in by("injection")]),
        "oos_refused": rate([r["refused"] for r in by("out_of_scope")]),
        "advice_seeking_flagged": rate([r["flagged"] for r in by("advice") + by("fact_specific")]),
        "n": len(rows),
    }
    return {"metrics": metrics, "items": rows, "failed": failed}


# 4 --------------------------------------------------------------------------------------------------------------

def run_abstention(m: Models) -> dict:
    items, failed = load("abstention.jsonl"), []
    rows = []
    for it, out in pmap(lambda it: answer(m, it["question"]), items, failed):
        titles = [c["title"] for c in out["claims"]]
        outcome = abstention_outcome(out["status"], out["draft"], out["claims"])
        rows.append({**it, "status": out["status"], "draft": out["draft"], "cited": sorted(set(titles)),
                     "unsourced": unsourced_authorities(out["draft"], cited_names(out["claims"])), "outcome": outcome,
                     "secondary_statute": out["flags"]["secondary_statute"], "risk": out["risk"],
                     "labelled": secondary_labelled(out["draft"], out["flags"]),
                     "acceptable": abstention_acceptable(outcome, out["draft"], out["flags"])})
    share = lambda o: rate([r["outcome"] == o for r in rows])  # noqa: E731
    # abstain_or_grounded: a secondary answer counts only when the draft is labelled and flagged (#18)
    metrics = {"no_invented_authority": rate([r["outcome"] != "invented" for r in rows]),
               "abstain_or_grounded": rate([r["acceptable"] for r in rows]),
               "secondary_labelled": rate([r["labelled"] for r in rows if r["outcome"] == "secondary"]),
               "abstained": share("abstained"), "secondary": share("secondary"), "invented": share("invented"),
               "n": len(rows)}
    return {"metrics": metrics, "items": rows, "failed": failed}


# 5 --------------------------------------------------------------------------------------------------------------

def _ranked(conn, m: Models, question: str) -> list[tuple]:
    hits = retrieve(conn, question, m.embed(question), rerank=m.rerank)
    covers = chunk_covers(conn, [int(h.chunk_id[1:]) for h in hits])
    return [(h.source["slug"], h.source["pinpoint"], covers[int(h.chunk_id[1:])]) for h in hits]


def run_robustness(m: Models) -> dict:
    gold = {g["id"]: g for g in load_gold()}
    variants = load("paraphrases.jsonl")
    originals = sorted({v["gold_id"] for v in variants})

    def work(q):
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            return _ranked(conn, m, q)
    failed = []
    base = dict(pmap(lambda gid: work(gold[gid]["question"]), originals, failed))
    # a variant whose original failed can't be compared; that original is already in `failed`
    rows = []
    for v, ranked in pmap(lambda v: work(v["question"]), [v for v in variants if v["gold_id"] in base], failed):
        expected = gold[v["gold_id"]]["expected"]
        rows.append({**v, "recall@8": recall_at_k(ranked, expected, K),
                     "original_recall@8": recall_at_k(base[v["gold_id"]], expected, K),
                     "overlap": round(jaccard([r[:2] for r in ranked], [r[:2] for r in base[v["gold_id"]]]), 3)})
    metrics = {"variant_recall@8": rate([r["recall@8"] for r in rows]),
               "original_recall@8": rate([base_r for base_r in {r["gold_id"]: r["original_recall@8"] for r in rows}.values()]),
               "mean_overlap": rate([r["overlap"] for r in rows])}
    for kind in ("lay", "legal", "typo"):
        metrics[f"recall@8_{kind}"] = rate([r["recall@8"] for r in rows if r["variant"] == kind])
    return {"metrics": metrics, "items": rows, "failed": failed}


# 6 --------------------------------------------------------------------------------------------------------------

def run_glossary(m: Models) -> dict:
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        terms = judged_sources(conn)

    def work(t):
        term, definition, where, text = t
        non = is_non_answer(definition)
        verdict = judge_definition(term, definition, where, text, m.judge) if text else \
            {"faithful": None, "reason": "no source section", "error": "no_source"}
        return {"term": term, "definition": definition, "source": where, "non_answer": non, **verdict}
    failed = []
    rows = [row for _, row in pmap(work, terms, failed, workers=4)]
    metrics = {"n": len(rows), "non_answer_rate": rate([r["non_answer"] for r in rows]),
               "faithful": rate([r["faithful"] for r in rows]), "no_source": sum(r["error"] == "no_source" for r in rows),
               "judge_errors": sum(r["error"] == "judge_error" for r in rows)}
    return {"metrics": metrics, "items": rows, "failed": failed}


EVALS = {"pinpoint": run_pinpoint, "search": run_search, "safety": run_safety, "abstention": run_abstention,
         "robustness": run_robustness, "glossary": run_glossary}


def main() -> int:
    names = sys.argv[1:] or list(EVALS)
    unknown = [n for n in names if n not in EVALS]
    if unknown:
        sys.exit(f"unknown eval(s): {unknown}; choose from {list(EVALS)}")
    RUNS.mkdir(parents=True, exist_ok=True)
    m, failures = Models(), 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for name in names:
        t0 = time.monotonic()
        try:
            result = EVALS[name](m)
        except Exception as e:  # the eval itself broke (not one item): record it and run the others
            result = {"metrics": {}, "items": [], "failed": [{"item": None, "error": repr(e)}]}
        failed = result["failed"]
        checks = passed(name, result["metrics"])
        ok = all(checks.values()) and not failed  # partial results never count as a pass
        failures += not ok
        report = {"eval": name, "metrics": result["metrics"], "thresholds": THRESHOLDS[name], "passed": checks,
                  "seconds": round(time.monotonic() - t0), "failed": failed, "items": result["items"]}
        path = RUNS / f"{stamp}-suite-{name}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        note = f"  {len(failed)} items failed (first: {failed[0]['error']})" if failed else ""
        print(f"[{'PASS' if ok else 'FAIL'}] {name:<11} {json.dumps(result['metrics'])}{note}  "
              f"({report['seconds']} s) → {path.relative_to(ROOT)}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
