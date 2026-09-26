"""Report which v0 laws were found in the downloaded A2AJ files.

Run: uv run scripts/match_v0.py   (exit 1 if any law is not matched)
"""
import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.v0 import V0, match_v0  # noqa: E402

A2AJ = Path(__file__).resolve().parent.parent / "input" / "a2aj"
COLUMNS = ["dataset", "name_en", "citation_en", "num_sections_en", "document_date_en"]


def load_rows() -> list[dict]:
    rows = []
    for dataset in sorted({law.dataset for law in V0}):
        path = A2AJ / f"{dataset}.parquet"
        if not path.exists():
            sys.exit(f"missing {path}; run: uv run scripts/fetch_a2aj.py")
        rows += pq.read_table(path, columns=COLUMNS).to_pylist()
    return rows


def main() -> int:
    results = match_v0(load_rows())
    for m in results:
        if m.row:
            detail = f"{m.row['citation_en']:<24} {m.row['num_sections_en']:>4} sections  as of {str(m.row['document_date_en'])[:10]}"
        else:
            detail = f"closest: {m.candidates or 'none'}"
        print(f"[{m.status:<14}] {m.law.title:<42} {detail}", flush=True)
    matched = sum(m.status == "matched" for m in results)
    print(f"{matched}/{len(results)} matched", flush=True)
    return 0 if matched == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
