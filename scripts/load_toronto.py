"""Load the downloaded Toronto Municipal Code chapters (see fetch_toronto.py) into documents + sections. Idempotent.

Run: uv run -m scripts.load_toronto   (then scripts/embed_chunks.py)
"""
import os
import re
import sys
from pathlib import Path

import psycopg

from ingest.bylaws import clean_lines, parse_chapter, pdf_text
from ingest.manifest import read_manifest
from ingest.statutes import load_document

ROOT = Path(__file__).resolve().parent.parent

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")


def main() -> int:
    entries = [e for e in read_manifest(ROOT / "input" / "manifest.jsonl") if e["source"] == "toronto-municipal-code"]
    latest = {e["url"]: e for e in entries}  # last line per URL wins
    problems = 0
    with psycopg.connect(DATABASE_URL) as conn:
        for e in latest.values():
            chapter, title = re.match(r"Toronto Municipal Code, Chapter (\d+), (.+)$", e["title"]).groups()
            raw = pdf_text(ROOT / e["path"])
            parsed = parse_chapter(raw, chapter, title, e["sha256"], e["url"], e["upstream_license"])
            status = load_document(conn, parsed)
            conn.commit()
            got = [s["pinpoint"] for s in parsed.sections if s["kind"] == "section"]
            toc = {f"{chapter}-{n}" for n in re.findall(rf"^§ {chapter}-(\d+(?:\.\d+)*)\.", "\n".join(clean_lines(raw, chapter)), re.M)}
            missing = sorted(toc - set(got))
            problems += bool(missing)
            print(f"[{status:<9}] ch. {chapter:<4} {len(got):>3} sections (TOC lists {len(toc)})"
                  f"  as of {parsed.document['in_force_from']}" + (f"  MISSING {missing}" if missing else ""), flush=True)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
