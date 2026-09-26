"""Build chunks for every loaded document and embed the ones that changed. Idempotent and resumable.

Run: uv run -m scripts.embed_chunks
"""
import os
import sys
import time

import psycopg

from ingest.chunks import embed_pending, load_sections, plan_chunks, plan_decision_chunks, sync_chunks
from ingest.vertex import EMBED_MODEL, embedder, make_client

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
WORKERS = 8


def main() -> int:
    start = time.monotonic()
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        docs = conn.execute("SELECT id, slug, title, kind, citation FROM documents ORDER BY id").fetchall()
        quiet = 0
        for doc_id, slug, title, kind, citation in docs:
            sections = load_sections(conn, doc_id)
            planned = plan_decision_chunks(title, citation, sections) if kind == "decision" else plan_chunks(title, sections)
            status, reused = sync_chunks(conn, doc_id, planned)
            if kind == "decision":  # thousands of decisions: summarize instead of one line each
                quiet += 1
                continue
            print(f"[{status:<9}] {slug:<40} {len(planned):>5} chunks  {reused:>5} embeddings reused", flush=True)
        if quiet:
            print(f"{quiet} decisions synced", flush=True)

        pending_chars = conn.execute(
            "SELECT count(*), coalesce(sum(length(text) + length(coalesce(context, ''))), 0) FROM chunks"
            " WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM %s", (EMBED_MODEL,),
        ).fetchone()
        print(f"embedding {pending_chars[0]} chunks (~{pending_chars[1] / 4 / 1000:.0f}k tokens) with {WORKERS} workers", flush=True)
        calls = embed_pending(conn, embedder(make_client()), model=EMBED_MODEL, workers=WORKERS)
        total, missing = conn.execute("SELECT count(*), count(*) FILTER (WHERE embedding IS NULL) FROM chunks").fetchone()
    print(f"{calls} embedding calls; {total} chunks, {missing} without embedding; {time.monotonic() - start:.1f}s", flush=True)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
