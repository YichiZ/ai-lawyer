"""Sections -> chunks (one per section; long sections split at subsection/line boundaries) -> embeddings."""
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import psycopg
from pgvector import HalfVector
from pgvector.psycopg import register_vector

from ingest.statutes import display_pinpoint

# ponytail: ~800 tokens at ~4 chars/token; switch to count_tokens if a model limit gets tight.
LAW_KINDS = ["statute", "regulation", "bylaw", "web"]  # batch jobs (situate, summarize); retrieval: app.ask.RETRIEVAL_KINDS
CHUNK_CHAR_LIMIT = 3200
SKIP_TEXTS = {"[blank]"}  # A2AJ placeholders for sections covered by a range entry ("25-49 Omitted ...")
DECISION_CHUNK_CHARS = 2000  # ~500 tokens of whole paragraphs (design: decision windows)
FLUSH_EVERY = 25


def run_batched(conn: psycopg.Connection, fn: Callable, jobs, write: Callable, workers: int = 8) -> int:
    """fn(arg) for each (key, arg) in jobs on worker threads; write(key, result) on this thread only.

    Commits every FLUSH_EVERY results and again on failure, so a crash keeps finished work. Returns the calls made.
    """
    done: list = []

    def flush():
        if done:
            with conn.transaction():
                for key, result in done:
                    write(key, result)
            done.clear()

    calls = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, arg): key for key, arg in jobs}
        try:
            for fut in as_completed(futures):
                done.append((futures[fut], fut.result()))
                calls += 1
                if len(done) >= FLUSH_EVERY:
                    flush()
        finally:
            flush()
            pool.shutdown(cancel_futures=True)
    return calls


def load_sections(conn: psycopg.Connection, document_id: int) -> list[dict]:
    """A document's sections in reading order, each with its parent's pinpoint: the input plan_chunks expects."""
    rows = conn.execute(
        "SELECT s.id, s.pinpoint, s.kind, s.heading, s.text, p.pinpoint FROM sections s"
        " LEFT JOIN sections p ON p.id = s.parent_id WHERE s.document_id = %s ORDER BY s.sort_order",
        (document_id,),
    ).fetchall()
    return [dict(zip(("id", "pinpoint", "kind", "heading", "text", "parent"), r)) for r in rows]


def embed_input(context: str, text: str, situating: str | None = None) -> str:
    """What gets embedded: the deterministic header, the LLM situating sentences (3.5) if any, then the chunk text."""
    return f"{context}\n{situating}\n\n{text}" if situating else f"{context}\n\n{text}"


def _pack(pieces: list[tuple[list[int], str, str]], limit: int = CHUNK_CHAR_LIMIT) -> list[tuple[list[int], str, str]]:
    """Greedily join (ids, pinpoint, text) pieces with newlines while under the limit."""
    out: list[tuple[list[int], str, str]] = []
    for ids, pin, text in pieces:
        if out and len(out[-1][2]) + 1 + len(text) <= limit:
            prev_ids, prev_pin, prev_text = out[-1]
            out[-1] = (prev_ids + ids, prev_pin, prev_text + "\n" + text)
        else:
            out.append((ids, pin, text))
    return out


def _split(section: dict, subsections: list[dict]) -> list[tuple[list[int], str, str]]:
    if len(section["text"]) <= CHUNK_CHAR_LIMIT:
        return [([section["id"]], section["pinpoint"], section["text"])]
    if subsections and "\n".join(s["text"] for s in subsections) == section["text"]:
        pieces = [([s["id"]], s["pinpoint"], s["text"]) for s in subsections]
    else:  # no clean subsections: split on lines, never mid-line
        pieces = [([], section["pinpoint"], line) for line in section["text"].split("\n")]
    packed = _pack(pieces)
    return [([section["id"]] + [i for i in ids if i != section["id"]], pin, text) for ids, pin, text in packed]


def plan_chunks(doc_title: str, sections: list[dict]) -> list[dict]:
    """sections in reading order: dicts with id, pinpoint, kind, heading, text, parent (pinpoint or None)."""
    children: dict[str, list[dict]] = {}
    for s in sections:
        if s["kind"] == "subsection":
            children.setdefault(s["parent"], []).append(s)
    chunks = []
    for s in sections:
        if s["kind"] != "section" or s["text"].strip() in SKIP_TEXTS:
            continue
        context = f"{doc_title} — {display_pinpoint(s['pinpoint'])}" + (f" — {s['heading']}" if s["heading"] else "")
        for ids, pin, text in _split(s, children.get(s["pinpoint"], [])):
            chunks.append({
                "pinpoint": pin,
                "section_ids": ids,
                "text": text,
                "context": context,
                "text_sha256": hashlib.sha256(embed_input(context, text).encode()).hexdigest(),
            })
    return chunks


def plan_decision_chunks(name: str, citation: str, sections: list[dict]) -> list[dict]:
    """Windows of whole numbered paragraphs (~500 tokens); the intro/headnote is not chunked."""
    paras = []
    for s in sections:
        if s["kind"] != "section":
            continue
        if len(s["text"]) <= DECISION_CHUNK_CHARS:
            paras.append(s)
            continue
        # Oversized paragraph (old decisions without [N] markers are one "paragraph"): split on line boundaries,
        # keeping the paragraph's pinpoint — never invent paragraph numbers the court did not publish.
        for _, _, piece in _pack([([s["id"]], s["pinpoint"], line) for line in s["text"].split("\n")],
                                 DECISION_CHUNK_CHARS):
            paras.append({**s, "text": piece})
    windows: list[list[dict]] = []
    for p in paras:
        if (windows and sum(len(x["text"]) + 1 for x in windows[-1]) + len(p["text"]) <= DECISION_CHUNK_CHARS
                and windows[-1][-1]["pinpoint"] != p["pinpoint"]):
            windows[-1].append(p)
        else:
            windows.append([p])
    chunks = []
    for w in windows:
        first, last = w[0]["pinpoint"][5:], w[-1]["pinpoint"][5:]
        context = f"{name}, {citation} — " + (f"para {first}" if first == last else f"paras {first}–{last}")
        text = "\n".join(p["text"] for p in w)
        chunks.append({"pinpoint": w[0]["pinpoint"], "section_ids": list(dict.fromkeys(p["id"] for p in w)), "text": text,
                       "context": context,
                       "text_sha256": hashlib.sha256(embed_input(context, text).encode()).hexdigest()})
    return chunks


def sync_chunks(conn: psycopg.Connection, document_id: int, planned: list[dict]) -> tuple[str, int]:
    """Make the document's chunks match `planned`, keeping embeddings whose text hash is unchanged.

    Returns ("unchanged", 0) or ("replaced", number of embeddings reused).
    """
    register_vector(conn)
    with conn.transaction():
        existing = conn.execute(
            "SELECT pinpoint, text_sha256, embedding, embedding_model, situating FROM chunks WHERE document_id = %s"
            " ORDER BY id", (document_id,),
        ).fetchall()
        if [(p, h) for p, h, _, _, _ in existing] == [(c["pinpoint"], c["text_sha256"]) for c in planned]:
            return "unchanged", 0
        cached = {h: (e, m) for _, h, e, m, _ in existing if e is not None}
        situated = {h: sit for _, h, _, _, sit in existing if sit}
        conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
        reused = 0
        for c in planned:
            emb, model = cached.get(c["text_sha256"], (None, None))
            reused += emb is not None
            conn.execute(
                "INSERT INTO chunks (document_id, section_ids, pinpoint, text, context, text_sha256, embedding,"
                " embedding_model, situating) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (document_id, c["section_ids"], c["pinpoint"], c["text"], c["context"], c["text_sha256"], emb, model,
                 situated.get(c["text_sha256"])),
            )
    return "replaced", reused


def embed_pending(conn: psycopg.Connection, embed: Callable[[str], list[float]], model: str, workers: int = 8) -> int:
    """Embed chunks with no embedding (or another model's). Commits every FLUSH_EVERY results, so a crash resumes.

    `embed` is called from worker threads; only this thread touches the database. Returns the number of calls made.
    """
    register_vector(conn)
    pending = conn.execute(
        "SELECT id, context, text, situating FROM chunks WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM %s"
        " ORDER BY id",
        (model,),
    ).fetchall()
    return run_batched(
        conn, embed, ((cid, embed_input(ctx or "", text, sit)) for cid, ctx, text, sit in pending),
        lambda cid, values: conn.execute("UPDATE chunks SET embedding = %s, embedding_model = %s WHERE id = %s",
                                         (HalfVector(values), model, cid)),
        workers)
