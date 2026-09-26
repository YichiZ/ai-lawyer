"""Phase 4.1: plain-language summaries for every eligible section (gemini-3.7-flash). Idempotent.

Run: uv run --env-file .env scripts/summarize_sections.py [--estimate]
"""
import os
import sys
import time
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.summaries import MIN_CHARS, PLACEHOLDERS, source_hash, summarize_pending  # noqa: E402
from ingest.vertex import ANSWER_MODEL, make_client, text_generator  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
PRICE_IN, PRICE_OUT = 0.75, 3.75  # USD / 1M tokens, gemini-3.7-flash introductory pricing to 2026-12-31 (checked 2026-09-26)
PROMPT_TOKENS, OUTPUT_TOKENS = 250, 110


def main() -> int:
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        rows = conn.execute("SELECT text, summary_source_hash FROM sections WHERE kind = 'section'").fetchall()
        todo = [t for t, h in rows if len(t.strip()) >= MIN_CHARS and not t.strip().startswith(PLACEHOLDERS)
                and h != source_hash(t)]
        tokens_in = sum(len(t) for t in todo) / 4 + len(todo) * PROMPT_TOKENS
        cost = tokens_in / 1e6 * PRICE_IN + len(todo) * OUTPUT_TOKENS / 1e6 * PRICE_OUT
        print(f"{len(todo)} sections to summarize, ~{tokens_in / 1e6:.1f}M input tokens, estimated ${cost:.2f}", flush=True)
        if "--estimate" in sys.argv or not todo:
            return 0
        t = time.monotonic()
        client = make_client(attempts=8, initial_delay=2.0, max_delay=60.0, timeout_ms=60_000)
        calls = summarize_pending(conn, text_generator(client, model=ANSWER_MODEL), workers=6)
    print(f"{calls} summaries in {time.monotonic() - t:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
