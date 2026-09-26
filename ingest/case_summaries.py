"""Plain-language decision summaries (Phase 5.5) by gemini-3.5-flash-lite from an excerpt (headnote + opening and
closing paragraphs, capped) to stay within budget; keyed on the document sha256 + prompt version."""
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import psycopg

PROMPT_VERSION = 1
MAX_CHARS = 24_000  # ~6k tokens per decision
OPENING, CLOSING = 30, 5
PROMPT = """Summarize this Ontario Court of Appeal / Supreme Court of Canada decision for a paralegal or law student.

{title}, {citation}
<excerpt>
{text}
</excerpt>

In 3 short sentences (grade 8-10 reading level): what happened (facts), what the court decided (outcome), and why it
matters for injury law. Use only the excerpt; if the outcome is not in it, say "The outcome is not in this excerpt."
Not legal advice. Reply with the summary only."""


def excerpt_for_summary(intro: str, paras: list[str]) -> str:
    chosen = list(enumerate(paras, 1))
    if len(chosen) > OPENING + CLOSING:
        chosen = chosen[:OPENING] + chosen[-CLOSING:]
    parts, size = [intro[:2000]] if intro else [], 0
    closing = [f"[{n}] {t}" for n, t in chosen[-CLOSING:]]
    budget = MAX_CHARS - sum(len(p) for p in closing) - sum(len(p) for p in parts)
    for n, t in chosen[:-CLOSING] if len(chosen) > CLOSING else []:
        piece = f"[{n}] {t}"
        if size + len(piece) > budget:
            break
        parts.append(piece)
        size += len(piece)
    return "\n".join(parts + (closing if len(chosen) > CLOSING else [f"[{n}] {t}" for n, t in chosen]))


def _hash(doc_sha: str) -> str:
    return hashlib.sha256(f"{PROMPT_VERSION}:{doc_sha}".encode()).hexdigest()


def summarize_cases(conn: psycopg.Connection, generate: Callable[[str], str], workers: int = 6) -> int:
    docs = conn.execute("SELECT id, title, neutral_citation, sha256, summary_source_hash FROM documents"
                        " WHERE kind = 'decision' ORDER BY id").fetchall()
    jobs = []
    for doc_id, title, citation, sha, old in docs:
        if old == _hash(sha):
            continue
        rows = conn.execute("SELECT kind, text FROM sections WHERE document_id = %s ORDER BY sort_order", (doc_id,)).fetchall()
        intro = next((t for k, t in rows if k == "part"), "")
        paras = [t for k, t in rows if k == "section"]
        jobs.append((doc_id, _hash(sha), PROMPT.format(title=title, citation=citation, text=excerpt_for_summary(intro, paras))))
    calls = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(generate, p): (doc_id, h) for doc_id, h, p in jobs}
        for fut in as_completed(futures):
            doc_id, h = futures[fut]
            conn.execute("UPDATE documents SET plain_summary = %s, summary_source_hash = %s WHERE id = %s",
                         (" ".join(fut.result().split()), h, doc_id))
            calls += 1
    return calls
