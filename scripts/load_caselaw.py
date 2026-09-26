"""Phase 5.3: load injury-relevant ONCA + SCC decisions into documents + sections (numbered paragraphs). Idempotent.

Run: uv run scripts/load_caselaw.py   (then scripts/embed_chunks.py)
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
from ingest.caselaw import is_injury_case, parse_decision  # noqa: E402
from ingest.statutes import load_document  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
COLUMNS = ["dataset", "citation_en", "name_en", "document_date_en", "url_en", "unofficial_text_en", "upstream_license"]


def main() -> int:
    t0, outcome, paras = time.monotonic(), Counter(), 0
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        for court in ("ONCA", "SCC"):
            for row in pq.read_table(ROOT / "input" / "a2aj" / f"{court}.parquet", columns=COLUMNS).to_pylist():
                text = row["unofficial_text_en"] or ""
                year = row["document_date_en"].year if row["document_date_en"] else None
                if not text or not row["citation_en"] or not is_injury_case(court, text, year):
                    continue
                parsed = parse_decision(row)
                outcome[load_document(conn, parsed)] += 1
                paras += sum(s["kind"] == "section" for s in parsed.sections)
    print(f"{dict(outcome)}; {paras} paragraphs; {time.monotonic() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
