"""Faithfulness check for decision summaries (Phase 5): Flash-Lite judge vs the excerpt the summary was written from.

Run: uv run --env-file .env -m scripts.judge_case_summaries [n=30]   (fixed sample; ~n cheap calls; saved to evals/runs/)
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from evals.answers import JUDGE_MODEL
from evals.readability import fk_grade
from evals.summaries import judge_summary, summarize_scores
from ingest.case_summaries import excerpt_for_summary
from ingest.vertex import batch_client, json_generator

ROOT = Path(__file__).resolve().parent.parent

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        docs = conn.execute("SELECT id, slug, title, neutral_citation, plain_summary FROM documents WHERE kind = 'decision'"
                            " AND plain_summary IS NOT NULL ORDER BY md5(slug) LIMIT %s", (n,)).fetchall()
        items = []
        for doc_id, slug, title, citation, summary in docs:
            rows = conn.execute("SELECT kind, text FROM sections WHERE document_id = %s ORDER BY sort_order",
                                (doc_id,)).fetchall()
            intro = next((t for k, t in rows if k == "part"), "")
            items.append({"slug": slug, "where": f"{title}, {citation} (decision excerpt)", "summary": summary,
                          "text": excerpt_for_summary(intro, [t for k, t in rows if k == "section"])})
    judge = json_generator(batch_client(), model=JUDGE_MODEL)
    with ThreadPoolExecutor(max_workers=4) as pool:
        verdicts = list(pool.map(lambda i: judge_summary(i["text"], i["summary"], judge, i["where"]), items))
    rows = [{"slug": i["slug"], "summary": i["summary"], **v, "grade": fk_grade(i["summary"])} for i, v in zip(items, verdicts)]
    report = summarize_scores(rows)
    out = ROOT / "evals" / "runs" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-decision-summary-judge.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": report, "items": rows}, indent=2, ensure_ascii=False))
    print(json.dumps(report))
    for r in rows:
        if r["faithful"] == 0.0:
            print(f"- {r['slug']}: {r['unsupported']} — {r['reason'][:200]}")
    print(f"saved {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
