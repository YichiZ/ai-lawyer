"""POST /ask: hybrid retrieval -> grounding gate -> Gemini claims -> quote verification in code -> pending_review draft.

Code, not the model, decides which citations survive: a quote must be an exact (normalized) substring of the chunk it
names, and that chunk must be one we retrieved.
"""
import json
from dataclasses import dataclass, field
from typing import Callable

import psycopg
from pgvector import HalfVector
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from app import tracing
from app.authorities import SECONDARY_LABEL, secondary_statutes
from app.format import mcgill_citation
from app.laws import excerpt
from ingest.statutes import display_pinpoint

# Fusion tuned on the Phase 3 gold sweep (3.3): k 60 / equal weights buried vector #1 hits under keyword noise.
# k 10 + keyword weight 0.3: recall@8 0.887 -> 1.000, MRR 0.624 -> 0.847 (offline sweep). Vector-only scored
# MRR 0.919 but the gold set has few exact-term/citation queries, where keyword search earns its place.
RRF_K = 10
KEYWORD_WEIGHT = 0.3
CANDIDATES = 50  # per retriever
TOP_K = 8
# Cosine distance of the best vector hit above which we answer "not found" without a model call.
# 0.30 from the Phase 2 gold set: refuses 7/15 out-of-scope, 0/62 in-scope (user-approved 2026-09-25).
# ponytail: a vector-distance gate until the Phase 3 reranker gives a better relevance score.
GATE_MAX_DISTANCE = 0.30
MIN_QUOTE_CHARS = 12
NOT_FOUND_SOURCES = 3

Generate = Callable[[str, dict], dict]  # (prompt, response JSON schema) -> parsed JSON

CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {
        "in_scope": {"type": "boolean"},
        "scope_note": {"type": "string"},
        "answer": {"type": "string"},
        "claims": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "chunk_id": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["text", "chunk_id", "quote"],
        }},
    },
    "required": ["in_scope", "answer", "claims"],
}

PROMPT = """You are a research assistant for paralegals and law students studying Ontario personal-injury law.
Answer the research question using ONLY the numbered passages below. They are from Ontario statutes, regulations and
Toronto by-laws.

Rules:
- If the question is not about Ontario personal-injury law (or the related Toronto by-laws), set in_scope=false and
  put a short description of the topic in scope_note. Do not answer it.
- "answer": 2-3 plain sentences a law student can follow. State rules, not advice: never say whether someone has a
  case, never predict an outcome, never value a claim, never compute a specific deadline date.
- "claims": each claim is one statement from your answer, the id of the passage that supports it (e.g. "c12"), and a
  quote copied EXACTLY, word for word, from that passage (one sentence or clause, at least a few words).
  Never paraphrase inside a quote. Use only passage ids listed below.
- If the passages do not answer the question, return an empty claims list and say so in "answer".
{feedback}
Question: {question}

Passages:
{passages}
"""


@dataclass
class Retrieved:
    chunk_id: str
    text: str
    distance: float | None  # cosine distance from the vector retriever (None if keyword-only)
    source: dict
    score: float = 0.0


@dataclass
class AskResult:
    status: str  # drafted | not_found | out_of_scope | unverified
    draft_markdown: str
    claims: list[dict] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)
    retried: bool = False
    secondary_statute: list[str] = field(default_factory=list)  # laws named but only quoted by cited decisions (#18)


def normalize(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return " ".join(s.split())


def rrf(rankings: list[list[str]], k: int = RRF_K, weights: list[float] | None = None) -> list[tuple[str, float]]:
    """Weighted reciprocal rank fusion: score = sum w/(k + rank). Ties keep first-seen order."""
    scores: dict[str, float] = {}
    for ranking, w in zip(rankings, weights or [1.0] * len(rankings)):
        for rank, cid in enumerate(ranking, start=1):
            scores[cid] = scores.get(cid, 0.0) + w / (k + rank)
    return sorted(scores.items(), key=lambda kv: -kv[1])


def verify_claims(claims: list[dict], chunks: dict[str, str]) -> tuple[list[dict], list[dict]]:
    ok, dropped = [], []
    for c in claims:
        quote = normalize(c.get("quote", ""))
        if c.get("chunk_id") not in chunks:
            dropped.append({**c, "reason": "chunk_not_retrieved"})
        elif len(quote) < MIN_QUOTE_CHARS:
            dropped.append({**c, "reason": "quote_too_short"})
        elif quote not in normalize(chunks[c["chunk_id"]]):
            dropped.append({**c, "reason": "quote_not_in_chunk"})
        else:
            ok.append(c)
    return ok, dropped


def _cite(source: dict) -> str:
    c = source["citation"]
    return f"*{c['title']}*, {c['reference']}" if c["title"] else c["reference"]


def compose_draft(answer: str, claims: list[dict]) -> str:
    """claims carry their "source" (see run_ask), so each quote is cited at its most precise pinpoint."""
    parts = [answer.strip(), "", "**What the law says**", ""]
    for c in claims:
        parts += [f"> {normalize(c['quote'])}", f"> — {_cite(c['source'])}", ""]
    return "\n".join(parts).strip()


def _not_found(hits: list[Retrieved]) -> AskResult:
    closest = sorted((h for h in hits if h.distance is not None), key=lambda h: h.distance)[:NOT_FOUND_SOURCES]
    lines = ["This was not found in the laws we cover. The closest passages were:", ""]
    lines += [f"- {_cite(h.source)}" for h in closest]
    return AskResult(status="not_found", draft_markdown="\n".join(lines))


Refine = Callable[[list[dict]], list[dict]]


def run_ask(question: str, hits: list[Retrieved], generate: Generate, refine: Refine = lambda claims: claims) -> AskResult:
    """`refine` narrows each verified claim's source (e.g. to the subsection holding the quote) before composing.
    The grounding gate looks at law hits only (its threshold was calibrated on them)."""
    best = min((h.distance for h in hits if h.distance is not None and h.source.get("kind") != "decision"),
               default=None)
    if best is None or best > GATE_MAX_DISTANCE:
        return _not_found(hits)

    chunks = {h.chunk_id: h.text for h in hits}
    sources = {h.chunk_id: h.source for h in hits}
    passages = "\n\n".join(f"[{h.chunk_id}] {_cite(h.source)}\n{h.text}" for h in hits)
    all_dropped, feedback = [], ""
    for attempt in range(2):
        prompt = PROMPT.format(question=question, passages=passages, feedback=feedback)
        with tracing.observe("generate", as_type="generation", input=prompt, metadata={"attempt": attempt + 1}) as gen:
            out = generate(prompt, CLAIMS_SCHEMA)
            gen.update(output=out)
        if not out.get("in_scope", True):
            note = out.get("scope_note") or "that topic"
            return AskResult(status="out_of_scope", draft_markdown=(
                f"This guide covers Ontario personal-injury law only; the question is about {note}."))
        with tracing.observe("verify", input={"claims": out.get("claims", [])}) as ver:
            ok, dropped = verify_claims(out.get("claims", []), chunks)
            ver.update(output={"kept": len(ok), "dropped": [{"chunk_id": d.get("chunk_id"), "reason": d["reason"]} for d in dropped]})
        all_dropped += dropped
        if ok:
            ok = refine([{**c, "source": sources[c["chunk_id"]]} for c in ok])
            secondary = secondary_statutes(out["answer"], [c["source"] for c in ok])
            draft = compose_draft(out["answer"], ok)
            return AskResult("drafted", f"{SECONDARY_LABEL}\n\n{draft}" if secondary else draft, ok, all_dropped,
                             retried=attempt > 0, secondary_statute=secondary)
        feedback = ("\nYour previous quotes were not exact copies of the passages. Copy each quote character for "
                    "character from the passage you cite.\n")
    return AskResult(status="unverified", draft_markdown="No statement could be verified against the passages.",
                     dropped=all_dropped, retried=True)


# --- database side ---

LAW_KINDS = ["statute", "regulation", "bylaw", "web"]  # web: official pages a reviewer added (6.2); decisions separately


def retrieve_for_answer(conn: psycopg.Connection, question: str, query_vector: list[float],
                        rerank: Callable[[str, list, int], list] | None = None) -> list[Retrieved]:
    """What the answer model reads: the law top TOP_K, then the decision top CASE_K, each ranked separately."""
    laws = retrieve(conn, question, query_vector, rerank=rerank)
    cases = retrieve(conn, question, query_vector, top_k=CASE_K, rerank=rerank, kinds=["decision"])
    return laws + cases


def keyword_ranking(conn: psycopg.Connection, question: str, limit: int = CANDIDATES,
                    kinds: list[str] = LAW_KINDS) -> list[int]:
    """Chunk ids by ts_rank_cd over any of the question's terms (all-terms-first was tried in 3.3, not kept)."""
    return [r[0] for r in conn.execute(
        "WITH t AS (SELECT replace(plainto_tsquery('english', %s)::text, '&', '|')::tsquery AS q)"
        " SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id, t"
        " WHERE d.kind = ANY(%s) AND t.q::text <> '' AND c.tsv @@ t.q"
        " ORDER BY ts_rank_cd(c.tsv, t.q) DESC LIMIT %s",
        (question, kinds, limit))]


def vector_ranking(conn: psycopg.Connection, query_vector: list[float], limit: int = CANDIDATES,
                   kinds: list[str] = LAW_KINDS) -> list[tuple[int, float]]:
    """(chunk id, cosine distance), nearest first."""
    register_vector(conn)
    vec = HalfVector(query_vector)
    return [(r[0], float(r[1])) for r in conn.execute(
        "SELECT c.id, c.embedding <=> %s FROM chunks c JOIN documents d ON d.id = c.document_id"
        " WHERE c.embedding IS NOT NULL AND d.kind = ANY(%s) ORDER BY c.embedding <=> %s LIMIT %s",
        (vec, kinds, vec, limit),
    )]


ALL_KINDS = LAW_KINDS + ["decision"]
CASE_K = 4  # decisions searched separately: mixing them into law retrieval dropped statute recall@8 1.000 -> 0.935


def retrieve(conn: psycopg.Connection, question: str, query_vector: list[float], top_k: int = TOP_K,
             rerank: Callable[[str, list, int], list] | None = None, kinds: list[str] = LAW_KINDS) -> list[Retrieved]:
    """Top CANDIDATES keyword (terms OR'ed) + top CANDIDATES vector, fused with weighted RRF; the top_k best.
    With `rerank`, the fused top RERANK_CANDIDATES are reordered by the reranker before cutting to top_k."""
    from app.rerank import RERANK_CANDIDATES

    register_vector(conn)
    cur = conn.cursor(row_factory=dict_row)
    keyword = keyword_ranking(conn, question, kinds=kinds)
    vector = vector_ranking(conn, query_vector, kinds=kinds)
    distance = {f"c{cid}": d for cid, d in vector}
    fused = rrf([[f"c{cid}" for cid in keyword], [f"c{cid}" for cid, _ in vector]], weights=[KEYWORD_WEIGHT, 1.0])[:RERANK_CANDIDATES if rerank else top_k]
    ids = [int(cid[1:]) for cid, _ in fused]
    rows = {r["id"]: r for r in cur.execute(
        "SELECT c.id, c.text, c.pinpoint, d.slug, d.title, d.short_name, d.kind, d.citation, d.reproduction"
        " FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.id = ANY(%s)", (ids,),
    ).fetchall()}
    hits = []
    for cid, score in fused:
        r = rows[int(cid[1:])]
        pin = r["pinpoint"]
        url = f"/cases/{r['slug']}#{pin}" if r["kind"] == "decision" else f"/laws/{r['slug']}/{pin}"
        source = {
            "chunk_id": cid, "slug": r["slug"], "title": r["title"], "pinpoint": pin,
            "display": display_pinpoint(pin), "citation": mcgill_citation(r, pin),
            "snippet": excerpt(r["text"]), "url": url, "kind": r["kind"],
        }
        hits.append(Retrieved(cid, r["text"], distance.get(cid), source, score))
    return rerank(question, hits, top_k) if rerank else hits


def create_pending(conn: psycopg.Connection, question: str, asked_by: int | None, hits: list[Retrieved],
                   timings: dict, trace_id: str | None) -> int:
    """The answer row as soon as sources are known; the draft is written later (see complete_draft)."""
    flags = {
        "status": "drafting",
        "best_distance": min((h.distance for h in hits if h.distance is not None), default=None),
        "sources": [{**h.source, "score": h.score, "distance": h.distance} for h in hits],
        "timings_ms": timings,
    }
    with conn.transaction():
        return conn.execute(
            "INSERT INTO answers (asked_by, question, flags, trace_id) VALUES (%s, %s, %s, %s) RETURNING id",
            (asked_by, question, json.dumps(flags), trace_id),
        ).fetchone()[0]


def complete_draft(conn: psycopg.Connection, answer_id: int, result: AskResult, draft_ms: int,
                   hits: list[Retrieved] | None = None) -> None:
    """Store the draft; `hits` (the reranked passages the draft used) replace the sources shown at ask time."""
    patch = {"status": result.status, "retried": result.retried, "dropped_claims": result.dropped,
             "secondary_statute": result.secondary_statute}
    if hits is not None:
        patch["sources"] = [{**h.source, "score": h.score, "distance": h.distance} for h in hits]
    with conn.transaction():
        conn.execute(
            "UPDATE answers SET draft_markdown = %s, claims = %s,"
            " flags = jsonb_set(flags || %s::jsonb, '{timings_ms,draft}', to_jsonb(%s::int)) WHERE id = %s",
            (result.draft_markdown, json.dumps(result.claims), json.dumps(patch), draft_ms, answer_id),
        )


def fail_draft(conn: psycopg.Connection, answer_id: int, error: str) -> None:
    """Drafting failed after retries: the reviewer sees a flagged placeholder to reject (or the researcher re-asks)."""
    with conn.transaction():
        conn.execute(
            "UPDATE answers SET draft_markdown = %s, flags = flags || %s::jsonb WHERE id = %s",
            ("This answer could not be drafted automatically. Reject it and ask the researcher to try again.",
             json.dumps({"status": "failed", "error": error[:300]}), answer_id),
        )


def store_answer(conn: psycopg.Connection, question: str, asked_by: int | None, result: AskResult,
                 hits: list[Retrieved], timings: dict, trace_id: str | None = None) -> int:
    """Create and complete in one go (tests and scripts)."""
    answer_id = create_pending(conn, question, asked_by, hits, timings, trace_id)
    complete_draft(conn, answer_id, result, timings.get("total", 0))
    return answer_id


def pinpoint_claims(conn: psycopg.Connection, claims: list[dict]) -> list[dict]:
    """Point each claim at the narrowest provision of its chunk whose text holds the quote: the one subsection
    (s 42 -> s 42(6)) or decision paragraph, else the section (a quote spanning subsections), else leave it.

    Driven by the chunk's own sections, not the chunk pinpoint: a split section's chunks are pinpointed at their first
    subsection (s-42-1), which has no children to search (issue #1).
    """
    cur = conn.cursor(row_factory=dict_row)
    out = []
    for c in claims:
        src = c["source"]
        rows = cur.execute(  # the chunk's sections plus their subsections (a whole section's chunk lists only its id)
            "SELECT s.pinpoint, s.kind, s.text, d.title, d.citation, d.kind AS doc_kind FROM chunks ch"
            " JOIN sections s ON s.id = ANY(ch.section_ids) OR s.parent_id = ANY(ch.section_ids)"
            " JOIN documents d ON d.id = s.document_id WHERE ch.id = %s", (int(c["chunk_id"][1:]),),
        ).fetchall()
        quote = normalize(c["quote"])
        holding = [r for r in rows if quote in normalize(r["text"])]
        subs = [r for r in holding if r["kind"] == "subsection"]
        secs = [r for r in holding if r["kind"] == "section"]
        r = subs[0] if len(subs) == 1 else secs[0] if len(secs) == 1 else None
        if r is None:
            out.append(c)
            continue
        pin = r["pinpoint"]
        url = f"/cases/{src['slug']}#{pin}" if r["doc_kind"] == "decision" else f"/laws/{src['slug']}/{pin}"
        out.append({**c, "source": {**src, "pinpoint": pin, "display": display_pinpoint(pin),
                                    "citation": mcgill_citation({**r, "kind": r["doc_kind"]}, pin), "url": url}})
    return out
