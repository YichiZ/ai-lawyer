"""Load the 12 v0 laws from input/a2aj/ into documents + sections. Idempotent.

Run: make db && uv run scripts/load_statutes.py
"""
import os
import sys
import time
from collections import Counter
from pathlib import Path

import psycopg
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.statutes import load_document, parse_law  # noqa: E402
from ingest.v0 import V0, match_v0  # noqa: E402

A2AJ = Path(__file__).resolve().parent.parent / "input" / "a2aj"
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")


def main() -> int:
    rows = []
    for dataset in sorted({law.dataset for law in V0}):
        rows += pq.read_table(A2AJ / f"{dataset}.parquet").to_pylist()
    results = match_v0(rows)
    unmatched = [m.law.slug for m in results if m.status != "matched"]
    if unmatched:
        sys.exit(f"not matched: {unmatched}; run scripts/match_v0.py")

    outcome = Counter()
    start = time.monotonic()
    with psycopg.connect(DATABASE_URL) as conn:
        for m in results:
            parsed = parse_law(m.row, m.law)
            kinds = Counter(s["kind"] for s in parsed.sections)
            no_heading = sum(1 for s in parsed.sections if s["kind"] == "section" and not s["heading"])
            status = load_document(conn, parsed)
            conn.commit()
            outcome[status] += 1
            print(f"[{status:<9}] {m.law.slug:<40} parts {kinds['part']:>3}  sections {kinds['section']:>4}"
                  f"  subsections {kinds['subsection']:>5}  no-heading {no_heading:>3}", flush=True)
    print(f"{dict(outcome)} in {time.monotonic() - start:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
