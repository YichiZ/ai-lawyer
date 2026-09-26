"""Try the current summary prompt on the eval sample without touching the DB: generate, judge, grade.
Run: uv run --env-file .env scripts/try_summary_prompt.py"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evals.answers import JUDGE_MODEL  # noqa: E402
from evals.readability import fk_grade  # noqa: E402
from evals.summaries import judge_summary, summarize_scores  # noqa: E402
from ingest.statutes import display_pinpoint  # noqa: E402
from ingest.summaries import build_prompt  # noqa: E402
from ingest.vertex import ANSWER_MODEL, json_generator, make_client, text_generator  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")

with psycopg.connect(DATABASE_URL) as conn:
    rows = conn.execute("SELECT d.slug, s.pinpoint, s.heading, s.text, d.title FROM sections s JOIN documents d ON d.id = s.document_id"
                        " WHERE s.plain_summary IS NOT NULL ORDER BY md5(d.slug || s.pinpoint) LIMIT 50").fetchall()
client = make_client(attempts=8, initial_delay=2.0, max_delay=60.0, timeout_ms=60_000)
write, judge = text_generator(client, model=ANSWER_MODEL), json_generator(client, model=JUDGE_MODEL)


def one(r):
    slug, pin, heading, text, title = r
    summary = write(build_prompt(title, display_pinpoint(pin), heading, text)).strip()
    return {**judge_summary(text, summary, judge, f"{title}, {display_pinpoint(pin)}"), "grade": fk_grade(summary),
            "slug": slug, "pinpoint": pin, "summary": summary}


with ThreadPoolExecutor(3) as pool:
    out = list(pool.map(one, rows))
print(summarize_scores(out))
for x in [o for o in out if o["faithful"] == 0][:5]:
    print(" -", x["slug"], x["pinpoint"], "|", x["unsupported"][:2], "|", x["reason"][:140])
print("example:", out[0]["summary"])
