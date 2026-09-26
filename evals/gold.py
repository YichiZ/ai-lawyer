"""The gold set: questions with the pinpoints that answer them and facts a correct answer must convey.

Every in-scope item is grounded: its expected pinpoints exist and each fact appears in their official text.
"""
import json
from pathlib import Path

import psycopg

GOLD_PATH = Path(__file__).resolve().parent / "gold.jsonl"
TOPICS = ("limitations", "city-claims", "slip-and-fall", "dog-bites", "motor-vehicle", "procedure-and-other", "case-law",
          "out-of-scope")


def norm(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return " ".join(s.casefold().split())


def load_gold(path: Path = GOLD_PATH) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _section_text(conn: psycopg.Connection, slug: str, pinpoint: str) -> str | None:
    row = conn.execute(
        "SELECT s.text FROM sections s JOIN documents d ON d.id = s.document_id WHERE d.slug = %s AND s.pinpoint = %s",
        (slug, pinpoint),
    ).fetchone()
    return row[0] if row else None


def validate_gold(items: list[dict], conn: psycopg.Connection) -> list[str]:
    """Return a list of human-readable errors; empty means the whole set is valid."""
    errors, seen = [], set()
    for item in items:
        iid = item.get("id") or ""
        where = iid or f"<item {item.get('question', '')[:30]!r}>"
        if not iid:
            errors.append(f"{where}: missing id")
        elif iid in seen:
            errors.append(f"{where}: duplicate id {iid}")
        seen.add(iid)
        if not (item.get("question") or "").strip():
            errors.append(f"{where}: missing question")
        if item.get("topic") not in TOPICS:
            errors.append(f"{where}: unknown topic {item.get('topic')!r}")

        if item.get("topic") == "out-of-scope":
            if item.get("must_refuse") is not True:
                errors.append(f"{where}: out-of-scope item must have must_refuse=true")
            if item.get("expected"):
                errors.append(f"{where}: out-of-scope item must have no expected pinpoints")
            continue

        if item.get("must_refuse"):
            errors.append(f"{where}: in-scope item marked must_refuse")
        expected = item.get("expected") or []
        if not expected:
            errors.append(f"{where}: no expected pinpoints")
        texts = []
        for e in expected:
            text = _section_text(conn, e.get("slug", ""), e.get("pinpoint", ""))
            if text is None:
                errors.append(f"{where}: pinpoint not found: {e.get('slug')} {e.get('pinpoint')}")
            else:
                texts.append(norm(text))
        facts = item.get("facts") or []
        if not facts:
            errors.append(f"{where}: no facts")
        for fact in facts:
            if texts and not any(norm(fact) in t for t in texts):
                errors.append(f"{where}: fact not in expected text: {fact!r}")
    return errors
