"""Build chunks for every loaded document and embed the ones that changed. Idempotent and resumable.

Run: uv run scripts/embed_chunks.py
"""
import os
import sys
import time
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.chunks import embed_pending, plan_chunks, sync_chunks  # noqa: E402
from ingest.vertex import EMBED_MODEL, embedder, make_client  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
WORKERS = 8


def main() -> int:
    start = time.monotonic()
    with psycopg.connect(DATABASE_URL) as conn:
        docs = conn.execute("SELECT id, slug, title FROM documents ORDER BY id").fetchall()
        for doc_id, slug, title in docs:
            rows = conn.execute(
                "SELECT s.id, s.pinpoint, s.kind, s.heading, s.text, p.pinpoint FROM sections s"
                " LEFT JOIN sections p ON p.id = s.parent_id WHERE s.document_id = %s ORDER BY s.sort_order",
                (doc_id,),
            ).fetchall()
            sections = [dict(zip(("id", "pinpoint", "kind", "heading", "text", "parent"), r)) for r in rows]
            planned = plan_chunks(title, sections)
            status, reused = sync_chunks(conn, doc_id, planned)
            print(f"[{status:<9}] {slug:<40} {len(planned):>5} chunks  {reused:>5} embeddings reused", flush=True)

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
