"""Validate a gold-set file against the loaded corpus. Exit 1 on any error.

Run: uv run scripts/check_gold.py [path]   (default evals/gold.jsonl)
"""
import os
import sys
from collections import Counter
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evals.gold import GOLD_PATH, load_gold, validate_gold  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else GOLD_PATH
    items = load_gold(path)
    with psycopg.connect(DATABASE_URL) as conn:
        errors = validate_gold(items, conn)
    for e in errors:
        print("  ERROR", e)
    bad = {e.split(":")[0] for e in errors}
    print(f"{len(items) - len(bad)}/{len(items)} valid  ·  " + ", ".join(f"{t} {n}" for t, n in sorted(Counter(i.get('topic') for i in items).items())))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
