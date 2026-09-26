"""Phase 3.5: write situating sentences for every chunk (Flash-Lite), then re-embed the changed chunks.

Run: uv run --env-file .env scripts/contextualize_chunks.py [--estimate | --clear]
  --estimate  print the cost estimate only
  --clear     remove all situating sentences and re-embed (revert)
"""
import os
import sys
import time
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.chunks import embed_pending  # noqa: E402
from ingest.contextualize import contextualize_pending  # noqa: E402
from ingest.vertex import EMBED_MODEL, embedder, make_client, text_generator  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
PRICE_IN, PRICE_OUT = 0.30, 2.50  # USD per 1M tokens, gemini-3.5-flash-lite (checked 2026-09-26)
OUTLINE_TOKENS, OUTPUT_TOKENS, PROMPT_TOKENS = 600, 80, 120  # rough per-call averages


def main() -> int:
    client = make_client(attempts=8, initial_delay=2.0, max_delay=60.0, timeout_ms=60_000)
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        if "--clear" in sys.argv:
            n = conn.execute("UPDATE chunks SET situating = NULL, embedding = NULL WHERE situating IS NOT NULL").rowcount
            conn.commit()
            print(f"cleared {n} chunks; re-embedding", flush=True)
        else:
            n, chars = conn.execute("SELECT count(*), coalesce(sum(length(text)), 0) FROM chunks WHERE situating IS NULL").fetchone()
            tokens_in = chars / 4 + n * (OUTLINE_TOKENS + PROMPT_TOKENS)
            cost = tokens_in / 1e6 * PRICE_IN + n * OUTPUT_TOKENS / 1e6 * PRICE_OUT
            print(f"{n} chunks to situate, ~{tokens_in / 1e6:.1f}M input tokens, estimated ${cost:.2f}", flush=True)
            if "--estimate" in sys.argv or n == 0:
                return 0
            t = time.monotonic()
            calls = contextualize_pending(conn, text_generator(client), workers=8)
            print(f"{calls} situating calls in {time.monotonic() - t:.0f}s", flush=True)
        t = time.monotonic()
        calls = embed_pending(conn, embedder(client), model=EMBED_MODEL, workers=8)
        missing = conn.execute("SELECT count(*) FROM chunks WHERE embedding IS NULL").fetchone()[0]
    print(f"{calls} embedding calls in {time.monotonic() - t:.0f}s; {missing} chunks without embedding", flush=True)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
