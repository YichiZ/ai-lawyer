"""Phase 5.5: plain-language summaries for loaded decisions (gemini-3.5-flash-lite). Idempotent.

Run: uv run --env-file .env scripts/summarize_cases.py [--estimate]
"""
import os
import sys
import time
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.case_summaries import MAX_CHARS, summarize_cases  # noqa: E402
from ingest.vertex import CHEAP_MODEL, make_client, text_generator  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
PRICE_IN, PRICE_OUT = 0.30, 2.50  # gemini-3.5-flash-lite, USD / 1M tokens (checked 2026-09-26)
BUDGET_LEFT = 11.0  # of the $25 approved, after ≈ $14 spent (see docs/iterations.md)


def main() -> int:
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        n = conn.execute("SELECT count(*) FROM documents WHERE kind = 'decision' AND summary_source_hash IS NULL").fetchone()[0]
        cost = n * (MAX_CHARS / 4) / 1e6 * PRICE_IN + n * 120 / 1e6 * PRICE_OUT  # upper bound: every excerpt at the cap
        print(f"{n} decisions to summarize, estimated ≤ ${cost:.2f} (budget left ≈ ${BUDGET_LEFT:.0f})", flush=True)
        if "--estimate" in sys.argv or n == 0:
            return 0
        if cost > BUDGET_LEFT:
            sys.exit("estimate exceeds the remaining approved budget — ask the user first")
        t = time.monotonic()
        client = make_client(attempts=8, initial_delay=2.0, max_delay=60.0, timeout_ms=60_000)
        calls = summarize_cases(conn, text_generator(client, model=CHEAP_MODEL), workers=6)
    print(f"{calls} decision summaries in {time.monotonic() - t:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
