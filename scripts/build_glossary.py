"""Phase 4.3: write glossary definitions for the curated terms, then judge each against its source text.

Run: uv run --env-file .env scripts/build_glossary.py
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evals.answers import JUDGE_MODEL  # noqa: E402
from evals.readability import fk_grade  # noqa: E402
from evals.summaries import judge_summary, summarize_scores  # noqa: E402
from ingest.glossary_build import load_terms, upsert_definitions  # noqa: E402
from ingest.statutes import display_pinpoint  # noqa: E402
from ingest.vertex import ANSWER_MODEL, json_generator, make_client, text_generator  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")


def main() -> int:
    client = make_client(attempts=8, initial_delay=2.0, max_delay=60.0, timeout_ms=60_000)
    terms = load_terms()
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        calls = upsert_definitions(conn, terms, text_generator(client, model=ANSWER_MODEL))
        rows = conn.execute(
            "SELECT g.term, g.plain_definition, d.title, g.source_pinpoint, s.text FROM glossary_terms g"
            " JOIN documents d ON d.slug = g.source_slug JOIN sections s ON s.document_id = d.id AND s.pinpoint = g.source_pinpoint"
        ).fetchall()
    judge = json_generator(client, model=JUDGE_MODEL)
    with ThreadPoolExecutor(3) as pool:
        verdicts = list(pool.map(lambda r: {**judge_summary(r[4], r[1], judge, f"{r[2]}, {display_pinpoint(r[3])}"),
                                            "grade": fk_grade(r[1]), "term": r[0], "definition": r[1]}, rows))
    print(f"{len(terms)} curated terms, {calls} new definitions, {len(rows)} in the glossary")
    print(summarize_scores(verdicts))
    for v in verdicts:
        if v["faithful"] == 0:
            print(f"  not faithful: {v['term']}: {v['definition']} | {v['reason'][:140]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
