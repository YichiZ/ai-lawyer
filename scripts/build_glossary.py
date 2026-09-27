"""Phase 4.3: write glossary definitions for the curated terms, then judge each against its source text.

Run: uv run --env-file .env -m scripts.build_glossary [--redo "term one;term two"]
Writes missing definitions, rewrites stored ones that fail the non-answer / source-reference check, and rewrites the
--redo terms (e.g. ones the judge found unfaithful or too narrow).
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import psycopg

from evals.answers import JUDGE_MODEL
from evals.readability import fk_grade
from evals.summaries import judge_summary, summarize_scores
from ingest.glossary_build import load_terms, upsert_definitions
from ingest.statutes import display_pinpoint
from ingest.vertex import ANSWER_MODEL, batch_client, json_generator, text_generator

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")


def main() -> int:
    redo = frozenset()
    if "--redo" in sys.argv:
        redo = frozenset(t.strip().lower() for t in sys.argv[sys.argv.index("--redo") + 1].split(";") if t.strip())
    client = batch_client()
    terms = load_terms()
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        calls = upsert_definitions(conn, terms, text_generator(client, model=ANSWER_MODEL), redo=redo)
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
