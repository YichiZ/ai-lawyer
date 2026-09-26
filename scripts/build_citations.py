"""Phase 5.4: citation graph for every loaded decision (A2AJ cited-case lists + statute references in the text).

Run: uv run scripts/build_citations.py
"""
import os
import sys
import time
from collections import Counter
from pathlib import Path

import psycopg
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest.citations import build_citations, statute_refs  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")


def main() -> int:
    t0, stats = time.monotonic(), Counter()
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        loaded = dict(conn.execute("SELECT neutral_citation, id FROM documents WHERE kind = 'decision'").fetchall())
        for court in ("ONCA", "SCC"):
            table = pq.read_table(ROOT / "input" / "a2aj" / f"{court}.parquet",
                                  columns=["citation_en", "unofficial_text_en", "cases_cited_en"])
            for r in table.to_pylist():
                doc_id = loaded.get(r["citation_en"])
                if doc_id is None:
                    continue
                refs = statute_refs(r["unofficial_text_en"] or "")
                stats["rows"] += build_citations(conn, doc_id, refs, list(r["cases_cited_en"] or []))
                stats["decisions"] += 1
        stats["statute_rows"], stats["statute_resolved"], stats["case_rows"], stats["case_in_corpus"] = conn.execute(
            "SELECT count(*) FILTER (WHERE kind = 'statute'), count(*) FILTER (WHERE kind = 'statute' AND cited_section_id IS NOT NULL),"
            " count(*) FILTER (WHERE kind = 'case'), count(*) FILTER (WHERE kind = 'case' AND cited_document_id IS NOT NULL) FROM citations"
        ).fetchone()
    print(f"{dict(stats)} in {time.monotonic() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
