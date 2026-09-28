"""POST /ask: hybrid retrieval -> grounding gate -> Gemini claims -> quote verification in code -> pending_review draft.

Code, not the model, decides which citations survive: a quote must be an exact (normalized) substring of the chunk it
names, and that chunk must be one we retrieved.
"""
import json
import re
from dataclasses import dataclass, field, replace
from typing import Callable

import psycopg
from pgvector import HalfVector
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from app import tracing
from app.authorities import SECONDARY_LABEL, secondary_statutes
from app.format import mcgill_citation, subtitle
from app.laws import excerpt
from ingest.citations import internal_refs
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
# Law retrieval searches statutes, regulations and by-laws only. Web pages a reviewer added (ingest.chunks.LAW_KINDS
# still includes them for the batch jobs) get their own small lane, like decisions: in the law lane an ontario.ca
# Small Claims page outranked Limitations Act s. 4 for "how long to sue" (gold lim-01 MRR 1.0 -> 0.5, issue #8).
RETRIEVAL_KINDS = ["statute", "regulation", "bylaw"]
WEB_K = 2  # web pages shown after the law hits, only when as close to the question as the grounding gate requires
CROSS_REF_K = 2  # chunks added per answer for provisions a retrieved law chunk refers to (#61)
REPEALED = re.compile(r"\s*(?:\([\w.]+\)\s*)?\[?(?:Repealed|Revoked)\b[^\n]*$", re.IGNORECASE)  # a stub, not a rule

Generate = Callable[[str, dict], dict]  # (prompt, response JSON schema) -> parsed JSON

CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {
        "in_scope": {"type": "boolean"},
        "advice_seeking": {"type": "boolean"},
        "scope_note": {"type": "string"},
        "answer": {"type": "string"},
        "claims": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "chunk_id": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["text", "chunk_id", "quote"],
        }},
    },
    "required": ["in_scope", "advice_seeking", "answer", "claims"],
}

PROMPT = """You are a research assistant for paralegals and law students studying Ontario personal-injury law.
Answer the research question using ONLY the numbered passages below. They are from Ontario statutes, regulations and
Toronto by-laws.

Rules:
- Scope is decided by the legal topic of the question, not by its wording or whether it names Ontario. In scope:
  civil claims for compensation by injured people in Ontario and their families: negligence, occupiers' liability,
  motor-vehicle accidents and accident benefits, municipal liability (roads, sidewalks), dog bites, limitation
  periods and notice rules, family members' claims under Family Law Act s. 61, workplace injuries under the Workplace
  Safety and Insurance Act, court procedure for these claims, and the related Toronto by-laws. What a law in the
  passages provides, including what conduct it makes an offence (e.g. trespass), is in scope.
- Out of scope, even when the question mentions an injury, an accident or Ontario: punishing offenders (sentences,
  fines, penalties, licence suspensions or pardons for criminal or provincial offences, including careless driving)
  and defending or contesting a charge or ticket (traffic, parking); other criminal law; family law other than
  Family Law Act s. 61 injury claims (divorce, custody, child or spousal support, property division); employment law
  (dismissal, severance, wages); landlord and tenant; defamation; tax; immigration; the law of any other province or
  country. For these set in_scope=false, put the topic in scope_note as a short noun phrase of 2-6 words with no
  period (e.g. "criminal sentencing"), and do not answer.
- Set advice_seeking=true if the question asks about the asker's own situation for a conclusion: whether they have a
  case or will win, what their claim is worth or what they would get, what they should do, or when their own deadline
  falls (they give their own date and ask for their deadline, or ask if it is too late). A question about what the
  rule is, even phrased with "I" or "my" ("I tripped on a sidewalk. How soon must I notify the City?"), is false.
- "answer": 2-3 plain sentences a law student can follow. State rules, not advice: never say whether someone has a
  case, never predict an outcome, never value a claim, never compute a specific deadline date.
- "claims": each claim is one statement from your answer, the id of the passage that supports it (e.g. "c12"), and a
  quote copied EXACTLY, word for word, from that passage (one sentence or clause, at least a few words).
  Never paraphrase inside a quote. Use only passage ids listed below.
- Each claim restates only what its own quote says, read on its own. Every detail in the answer and in each claim
  (a number, period, deadline, party, category, condition or exception) must appear in the quote of the claim that
  states it. A detail that is only in another provision or passage needs its own claim quoting it; if you cannot
  quote it, leave it out. Never combine two provisions in one claim: a provision that refers to another ("the
  obligation under subsection (2)") is one claim, and what the other provision says is a second claim with its own
  quote. Do not summarize a list more broadly than the quote does, and do not leave out a condition the quote sets.
- A passage marked "referred to by [cN]" holds a provision that passage cN refers to. If you state what cN says
  and it applies that provision ("in accordance with clause ..."), also state the conditions that provision sets
  (e.g. its opening words), each in its own claim quoting them, or do not state cN at all.
- Indexed amounts: if a rule's dollar figure is "the greater of X and the prescribed amount", is prescribed by
  regulation, or is revised or indexed over time, never present the base or dated figure as the current amount. Say
  the amount is indexed or prescribed, quote the passage that sets or indexes it if one is listed, and say the current
  figure is published separately and is not in these passages. Never calculate a current amount. Say an amount is
  indexed only as the quoted provision says, with every condition it sets (e.g. an optional benefit that must be
  purchased, or a period in which the accident occurred); a condition in a provision's opening words needs its own
  claim quoting those words. Never extend an indexing provision to amounts or accidents it does not cover.
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
    advice_seeking: bool = False  # the question asks for advice on the asker's own facts (#7)


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


def _referred(h: "Retrieved") -> str:
    by = h.source.get("referenced_by")
    return f" (referred to by [{by}])" if by else ""


def compose_draft(answer: str, claims: list[dict]) -> str:
    """claims carry their "source" (see run_ask), so each quote is cited at its most precise pinpoint."""
    parts = [answer.strip(), "", "**What the law says**", ""]
    for c in claims:
        parts += [f"> {normalize(c['quote'])}", f"> — {_cite(c['source'])}", ""]
    return "\n".join(parts).strip()


def out_of_scope_message(note: str | None) -> str:
    """The model's scope_note may be a noun phrase or a whole sentence (#15): keep its first clause, drop trailing
    punctuation, and give it its own sentence so its capitalization never lands mid-sentence."""
    topic = re.split(r"[;\n]|\.\s+(?=[A-Z])| falls under | is governed by ", (note or "").strip(), maxsplit=1)[0]
    topic = topic.strip(" .,:")
    topic = topic[:1].upper() + topic[1:] if topic else "Another area of law"
    return f"This guide covers Ontario personal-injury law only. Topic of this question: {topic}."


def _not_found(hits: list[Retrieved]) -> AskResult:
    closest = sorted((h for h in hits if h.distance is not None), key=lambda h: h.distance)[:NOT_FOUND_SOURCES]
    lines = ["This was not found in the laws we cover. The closest passages were:", ""]
    lines += [f"- {_cite(h.source)}" for h in closest]
    return AskResult(status="not_found", draft_markdown="\n".join(lines))


Refine = Callable[[list[dict]], list[dict]]


def run_ask(question: str, hits: list[Retrieved], generate: Generate, refine: Refine = lambda claims: claims,
            library_titles: list[str] = ()) -> AskResult:
    """`refine` narrows each verified claim's source (e.g. to the subsection holding the quote) before composing.
    The grounding gate looks at law hits only (its threshold was calibrated on them). `library_titles` (see
    library_titles()) keeps laws we hold from being labelled as quoted only by a decision."""
    best = min((h.distance for h in hits
                if h.distance is not None and h.source.get("kind") not in ("decision", "web")), default=None)
    if best is None or best > GATE_MAX_DISTANCE:
        return _not_found(hits)

    chunks = {h.chunk_id: h.text for h in hits}
    sources = {h.chunk_id: h.source for h in hits}
    passages = "\n\n".join(f"[{h.chunk_id}] {_cite(h.source)}{_referred(h)}\n{h.text}" for h in hits)
    all_dropped, feedback, advice = [], "", False
    for attempt in range(2):
        prompt = PROMPT.format(question=question, passages=passages, feedback=feedback)
        with tracing.observe("generate", as_type="generation", input=prompt, metadata={"attempt": attempt + 1}) as gen:
            out = generate(prompt, CLAIMS_SCHEMA)
            gen.update(output=out)
        advice = bool(out.get("advice_seeking"))
        if not out.get("in_scope", True):
            return AskResult(status="out_of_scope", draft_markdown=out_of_scope_message(out.get("scope_note")))
        with tracing.observe("verify", input={"claims": out.get("claims", [])}) as ver:
            ok, dropped = verify_claims(out.get("claims", []), chunks)
            ver.update(output={"kept": len(ok), "dropped": [{"chunk_id": d.get("chunk_id"), "reason": d["reason"]} for d in dropped]})
        all_dropped += dropped
        if ok:
            ok = refine([{**c, "source": sources[c["chunk_id"]]} for c in ok])
            secondary = secondary_statutes(out["answer"], [c["source"] for c in ok], library_titles)
            draft = compose_draft(out["answer"], ok)
            return AskResult("drafted", f"{SECONDARY_LABEL}\n\n{draft}" if secondary else draft, ok, all_dropped,
                             retried=attempt > 0, secondary_statute=secondary, advice_seeking=advice)
        feedback = ("\nYour previous quotes were not exact copies of the passages. Copy each quote character for "
                    "character from the passage you cite.\n")
    return AskResult(status="unverified", draft_markdown="No statement could be verified against the passages.",
                     dropped=all_dropped, retried=True, advice_seeking=advice)


# --- database side ---



def retrieve_for_answer(conn: psycopg.Connection, question: str, query_vector: list[float],
                        rerank: Callable[[str, list, int], list] | None = None) -> list[Retrieved]:
    """What the answer model reads: the law top TOP_K, the close web pages, then the decision top CASE_K, each ranked
    separately, then the provisions the law hits refer to (with_cross_references)."""
    laws = retrieve(conn, question, query_vector, rerank=rerank)
    cases = retrieve(conn, question, query_vector, top_k=CASE_K, rerank=rerank, kinds=["decision"])
    return with_cross_references(conn, laws + retrieve_web(conn, question, query_vector) + cases)


def retrieve_web(conn: psycopg.Connection, question: str, query_vector: list[float]) -> list[Retrieved]:
    """The web-page lane: the fused top WEB_K, dropping any page farther than the grounding gate allows."""
    hits = retrieve(conn, question, query_vector, top_k=WEB_K, kinds=["web"])
    return [h for h in hits if h.distance is not None and h.distance <= GATE_MAX_DISTANCE]


def keyword_ranking(conn: psycopg.Connection, question: str, limit: int = CANDIDATES,
                    kinds: list[str] = RETRIEVAL_KINDS) -> list[int]:
    """Chunk ids by ts_rank_cd over any of the question's terms (all-terms-first was tried in 3.3, not kept)."""
    return [r[0] for r in conn.execute(
        "WITH t AS (SELECT replace(plainto_tsquery('english', %s)::text, '&', '|')::tsquery AS q)"
        " SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id, t"
        " WHERE d.kind = ANY(%s) AND t.q::text <> '' AND c.tsv @@ t.q"
        " ORDER BY ts_rank_cd(c.tsv, t.q) DESC LIMIT %s",
        (question, kinds, limit))]


def vector_ranking(conn: psycopg.Connection, query_vector: list[float], limit: int = CANDIDATES,
                   kinds: list[str] = RETRIEVAL_KINDS) -> list[tuple[int, float]]:
    """(chunk id, cosine distance), nearest first."""
    register_vector(conn)
    vec = HalfVector(query_vector)
    return [(r[0], float(r[1])) for r in conn.execute(
        "SELECT c.id, c.embedding <=> %s FROM chunks c JOIN documents d ON d.id = c.document_id"
        " WHERE c.embedding IS NOT NULL AND d.kind = ANY(%s) ORDER BY c.embedding <=> %s LIMIT %s",
        (vec, kinds, vec, limit),
    )]


ALL_KINDS = RETRIEVAL_KINDS + ["decision"]
CASE_K = 4  # decisions searched separately: mixing them into law retrieval dropped statute recall@8 1.000 -> 0.935


def retrieve(conn: psycopg.Connection, question: str, query_vector: list[float], top_k: int = TOP_K,
             rerank: Callable[[str, list, int], list] | None = None, kinds: list[str] = RETRIEVAL_KINDS) -> list[Retrieved]:
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
        "SELECT c.id, c.text, c.pinpoint, d.slug, d.title, d.short_name, d.kind, d.citation, d.reproduction, d.url"
        " FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.id = ANY(%s)", (ids,),
    ).fetchall()}
    hits = [Retrieved(cid, rows[int(cid[1:])]["text"], distance.get(cid), _source(cid, rows[int(cid[1:])]), score)
            for cid, score in fused]
    return rerank(question, hits, top_k) if rerank else hits


def _source(cid: str, r: dict) -> dict:
    pin = r["pinpoint"]
    url = f"/cases/{r['slug']}#{pin}" if r["kind"] == "decision" else f"/laws/{r['slug']}/{pin}"
    return {
        "chunk_id": cid, "slug": r["slug"], "title": r["title"], "pinpoint": pin,
        "display": display_pinpoint(pin), "citation": mcgill_citation(r, pin),
        "snippet": excerpt(r["text"]), "url": url, "kind": r["kind"], "subtitle": subtitle(r),
    }


def with_cross_references(conn: psycopg.Connection, hits: list[Retrieved], cap: int = CROSS_REF_K) -> list[Retrieved]:
    """`hits` plus, at the end, up to `cap` chunks holding provisions of the same law that a retrieved statute or
    regulation chunk refers to ("in accordance with clause 268 (1.4) (b)"), one hop (#61). A condition set in the
    referenced provision is then in the passages. References that set the citing provision's terms ("in accordance
    with", "subject to") come first, then the rest; each group in rank order. The added hits have no distance or score
    (the grounding gate ignores them) and name the chunk that referred to them in source["referenced_by"]; a referenced
    chunk that was already retrieved keeps its place and only gets that label."""
    cur = conn.cursor(row_factory=dict_row)
    seen, added, labels = {h.chunk_id for h in hits}, [], {}
    refs = [(h, pin, terms) for h in hits if h.source.get("kind") in ("statute", "regulation")
            for pin, terms in internal_refs(h.text)]
    for h, pin, _ in sorted(refs, key=lambda ref: not ref[2]):  # stable: rank order within each group
        if len(added) >= cap:
            break
        r = cur.execute(  # the subsection's chunk, else (subsection not stored) the section's first chunk
            "SELECT c.id, c.text, c.pinpoint, d.slug, d.title, d.short_name, d.kind, d.citation, d.reproduction, d.url,"
            " s.text AS target_text FROM sections s JOIN documents d ON d.id = s.document_id"
            " JOIN chunks c ON c.document_id = d.id AND s.id = ANY(c.section_ids)"  # document_id: index, not seq scan
            " WHERE d.slug = %s AND s.pinpoint = ANY(%s) ORDER BY s.pinpoint = %s DESC, c.id LIMIT 1",
            (h.source["slug"], [pin, "-".join(pin.split("-")[:2])], pin)).fetchone()
        cid = f"c{r['id']}" if r else None
        if cid is None or cid == h.chunk_id or REPEALED.match(r["target_text"]):
            continue
        if cid in seen:  # already a passage: label it so the model still links the two
            labels.setdefault(cid, h)
            continue
        seen.add(cid)
        added.append(Retrieved(cid, r["text"], None, {**_source(cid, r), **_referred_by(h)}))
    labelled = [replace(h, source={**h.source, **_referred_by(labels[h.chunk_id])})
                if h.chunk_id in labels and "referenced_by" not in h.source else h for h in hits]
    return labelled + added


def _referred_by(h: Retrieved) -> dict:
    """The referring passage: its chunk id for the prompt label, its pinpoint for the answer page."""
    return {"referenced_by": h.chunk_id, "referenced_by_display": h.source.get("display")}


def library_titles(conn: psycopg.Connection) -> list[str]:
    """Titles, short names and citations of the laws we hold (every non-decision document)."""
    return [v for row in conn.execute("SELECT title, short_name, citation FROM documents WHERE kind <> 'decision'")
            for v in row if v]


STALE_DRAFT = "15 minutes"  # drafts take ~70 s at p95 with retries; older NULL drafts were lost


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


def result_flags(result: AskResult) -> dict:
    """The answer flags a draft result sets; risk_reasons() reads them (production and evals alike)."""
    return {"status": result.status, "retried": result.retried, "dropped_claims": result.dropped,
            "secondary_statute": result.secondary_statute, "advice_seeking": result.advice_seeking}


def complete_draft(conn: psycopg.Connection, answer_id: int, result: AskResult, draft_ms: int,
                   hits: list[Retrieved] | None = None) -> None:
    """Store the draft; `hits` (the reranked passages the draft used) replace the sources shown at ask time."""
    patch = result_flags(result)
    if hits is not None:
        patch["sources"] = [{**h.source, "score": h.score, "distance": h.distance} for h in hits]
    with conn.transaction():
        conn.execute(
            "UPDATE answers SET draft_markdown = %s, claims = %s,"
            " flags = jsonb_set(flags || %s::jsonb, '{timings_ms,draft}', to_jsonb(%s::int))"
            " WHERE id = %s AND status = 'pending_review'",  # a draft landing after review must not change it
            (result.draft_markdown, json.dumps(result.claims), json.dumps(patch), draft_ms, answer_id),
        )


FAILED_DRAFT = "This answer could not be drafted automatically. Reject it and ask the researcher to try again."


def fail_draft(conn: psycopg.Connection, answer_id: int, error: str) -> None:
    """Drafting failed after retries: the reviewer sees a flagged placeholder to reject (or the researcher re-asks)."""
    with conn.transaction():
        conn.execute(
            "UPDATE answers SET draft_markdown = %s, flags = flags || %s::jsonb"
            " WHERE id = %s AND status = 'pending_review'",
            (FAILED_DRAFT, json.dumps({"status": "failed", "error": error[:300]}), answer_id),
        )


def fail_stale_drafts(conn: psycopg.Connection, older_than: str = STALE_DRAFT) -> list[int]:
    """Drafting runs in the API process: a restart mid-draft leaves the draft NULL forever. Flag such answers failed
    so the reviewer sees them (a late draft still overwrites the placeholder)."""
    return [r[0] for r in conn.execute(  # one statement: a draft that lands first is never overwritten
        "UPDATE answers SET draft_markdown = %s, flags = flags || %s::jsonb"
        " WHERE status = 'pending_review' AND draft_markdown IS NULL AND created_at < now() - %s::interval"
        " RETURNING id",
        (FAILED_DRAFT, json.dumps({"status": "failed", "error": "drafting was interrupted (API restarted?)"}),
         older_than)).fetchall()]


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
