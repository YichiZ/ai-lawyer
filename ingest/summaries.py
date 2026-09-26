"""Plain-language section summaries (Phase 4.1), written by gemini-3.7-flash at grade 10.

Stored on `sections.plain_summary` with `summary_source_hash` = sha256(section text + prompt version), so only
new or changed sections (or a new prompt) are summarized again. Shown beside the official text, labelled as AI-written.
"""
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import psycopg

from ingest.statutes import display_pinpoint

PROMPT_VERSION = 3  # v2: no glosses/outside facts (glossary defines terms); v3: shorter sentences, short words (grade <= 10)
MIN_CHARS = 60
PLACEHOLDERS = ("[blank]", "Repealed", "Omitted", "Revoked")
FLUSH_EVERY = 25
PROMPT = """Rewrite this provision of Ontario law in plain language for a paralegal or law student.

{title}, {display}{heading}
<official_text>
{text}
</official_text>

Rules:
- At most 3 sentences, each under 14 words. Prefer short, everyday words; aim for a grade 8 reading level.
- Say what the rule is and who it applies to. Keep a legal term only if the rule needs it, and do not define it
  (a glossary does that).
- Use only what the text says: no outside facts, no examples, no definitions, no section numbers the text does not
  mention. If the text points to another section, just say "another section".
- This is not legal advice: never say whether someone has a case, predict outcomes, value a claim, or calculate a date.
Reply with the summary only."""


def eligible(section: dict) -> bool:
    text = (section.get("text") or "").strip()
    return section["kind"] == "section" and len(text) >= MIN_CHARS and not text.startswith(PLACEHOLDERS)


def source_hash(text: str) -> str:
    return hashlib.sha256(f"{PROMPT_VERSION}\n{text}".encode()).hexdigest()


def build_prompt(title: str, display: str, heading: str | None, text: str) -> str:
    return PROMPT.format(title=title, display=display, heading=f" — {heading}" if heading else "", text=text)


def summarize_pending(conn: psycopg.Connection, generate: Callable[[str], str], workers: int = 8) -> int:
    """Summarize eligible sections whose text or prompt changed since their last summary. Returns model calls."""
    rows = conn.execute(
        "SELECT s.id, s.kind, s.pinpoint, s.heading, s.text, s.summary_source_hash, d.title FROM sections s"
        " JOIN documents d ON d.id = s.document_id WHERE s.kind = 'section' ORDER BY s.id"
    ).fetchall()
    jobs = []
    for sid, kind, pin, heading, text, old_hash, title in rows:
        if eligible({"kind": kind, "text": text}) and old_hash != source_hash(text):
            jobs.append((sid, source_hash(text), build_prompt(title, display_pinpoint(pin), heading, text)))

    done: list[tuple[int, str, str]] = []

    def flush():
        if done:
            with conn.transaction():
                for sid, h, summary in done:
                    conn.execute("UPDATE sections SET plain_summary = %s, summary_source_hash = %s WHERE id = %s",
                                 (summary, h, sid))
            done.clear()

    calls = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(generate, prompt): (sid, h) for sid, h, prompt in jobs}
        try:
            for fut in as_completed(futures):
                sid, h = futures[fut]
                done.append((sid, h, fut.result().strip()))
                calls += 1
                if len(done) >= FLUSH_EVERY:
                    flush()
        finally:
            flush()
            pool.shutdown(cancel_futures=True)
    return calls
