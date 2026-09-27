"""HTTP API. Every response uses one envelope: {"data": ..., "error": {"code", "message"} | null, "meta": ... | null}.

Run: make api   (http://localhost:8000/docs)
"""
import logging
import os
import time
from functools import lru_cache
from typing import Annotated, Callable, ContextManager, Iterator, Literal

import psycopg
from fastapi import BackgroundTasks, Depends, FastAPI, Header, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from starlette.exceptions import HTTPException

from app import ask, cases, guides, jobs, laws, review, search, tracing, web_fallback
from app.rerank import RERANK_CANDIDATES, make_reranker
from ingest import vertex, web

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
SLUG = r"^[a-z0-9][a-z0-9.\-]*$"
RERANK_TIMEOUT_MS = 2_500  # sent to Vertex as a deadline: 1.6 s made 24/30 calls 504; 2.5 s: 0/30, rerank p95 1.5 s

log = logging.getLogger("app")
app = FastAPI(title="Ontario Injury Law Guide API")


def get_conn() -> Iterator[psycopg.Connection]:
    # ponytail: one connection per request; add psycopg_pool when concurrency matters.
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        yield conn


class VertexAI:
    """The two model calls /ask needs; replaced by a fake in tests."""

    def __init__(self):
        client = vertex.make_client()
        self.embed_query = vertex.embedder(client, task_type="RETRIEVAL_QUERY")
        self.generate = vertex.json_generator(client)
        # Interactive rerank fails fast (one 2.5 s attempt) and falls back to fused order; evals use a patient client.
        fast = vertex.make_client(attempts=1, timeout_ms=RERANK_TIMEOUT_MS)
        self.rerank = make_reranker(vertex.json_generator(fast, model=vertex.CHEAP_MODEL))
        self.search_web = lambda q: web_fallback.search_web(q, client, vertex.ANSWER_MODEL)


@lru_cache(maxsize=1)
def get_ai() -> VertexAI:
    if os.environ.get("AI_FAKE") == "1":  # end-to-end UI tests only: deterministic, no Vertex calls
        from app.fake_ai import FakeAI

        log.warning("AI_FAKE=1: using the deterministic fake model (tests only)")
        return FakeAI(lambda: psycopg.connect(DATABASE_URL, autocommit=True))
    return VertexAI()


def get_connect() -> Callable[[], ContextManager[psycopg.Connection]]:
    """Connection factory for work that outlives the request (background drafting)."""
    return lambda: psycopg.connect(DATABASE_URL, autocommit=True)


@lru_cache(maxsize=1)
def get_queue() -> jobs.Queue:
    import redis

    queue = jobs.Queue(redis.Redis.from_url(REDIS_URL, decode_responses=True))
    queue.ensure_group()
    return queue


Conn = Annotated[psycopg.Connection, Depends(get_conn)]
Connect = Annotated[Callable[[], ContextManager[psycopg.Connection]], Depends(get_connect)]
AI = Annotated[VertexAI, Depends(get_ai)]
JobQueue = Annotated[jobs.Queue, Depends(get_queue)]


def current_user(conn: Conn, x_demo_user: Annotated[Literal["researcher", "reviewer"], Header()] = "researcher") -> dict:
    """Demo only: the role comes from the X-Demo-User header (default researcher). No real authentication."""
    uid, name = conn.execute("SELECT id, name FROM users WHERE role = %s ORDER BY id LIMIT 1", (x_demo_user,)).fetchone()
    return {"id": uid, "name": name, "role": x_demo_user}


User = Annotated[dict, Depends(current_user)]


def require_reviewer(user: User) -> dict:
    if user["role"] != "reviewer":
        raise HTTPException(status_code=403, detail="Reviewers only")
    return user


Reviewer = Annotated[dict, Depends(require_reviewer)]
Slug = Annotated[str, Path(pattern=SLUG, max_length=120)]  # web page slugs are capped at 120 (ingest/web.py)
Pinpoint = Annotated[str, Path(pattern=SLUG, max_length=100)]


def envelope(data=None, error=None, meta=None, status=200) -> JSONResponse:
    return JSONResponse(jsonable_encoder({"data": data, "error": error, "meta": meta}), status_code=status)


class NotFound(HTTPException):
    def __init__(self, message: str):
        super().__init__(status_code=404, detail=message)




@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    code = {403: "forbidden", 404: "not_found", 409: "conflict"}.get(exc.status_code, "http_error")
    return envelope(error={"code": code, "message": str(exc.detail)}, status=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    fields = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors())
    return envelope(error={"code": "invalid_request", "message": f"Invalid value for: {fields}"}, status=422)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return envelope(error={"code": "internal_error", "message": "Something went wrong. Please try again."}, status=500)


@app.get("/laws")
def list_laws(conn: Conn):
    groups = laws.list_laws(conn)
    return envelope(groups, meta={"total": sum(len(g["documents"]) for g in groups)})


@app.get("/laws/{slug}")
def get_law(slug: Slug, conn: Conn):
    doc = laws.get_document(conn, slug)
    if not doc:
        raise NotFound(f"No law '{slug}'")
    tree = laws.law_tree(conn, doc["id"])
    return envelope({"document": {k: v for k, v in doc.items() if k != "id"}, "tree": tree})


@app.delete("/laws/{slug}")
def delete_law(slug: Slug, conn: Conn, reviewer: Reviewer):
    """Remove a web page from the library (its sections and chunks go with it). Other laws are never removed here."""
    kind = laws.delete_web_page(conn, slug)
    if kind is None:
        raise NotFound(f"No law '{slug}'")
    if kind != "web":
        raise HTTPException(status_code=409, detail="Only web pages can be removed from the library")
    log.info("web page %s removed by %s", slug, reviewer["name"])
    return envelope({"slug": slug, "deleted": True})


@app.get("/laws/{slug}/{pinpoint}")
def get_section(slug: Slug, pinpoint: Pinpoint, conn: Conn):
    doc = laws.get_document(conn, slug)
    if not doc:
        raise NotFound(f"No law '{slug}'")
    section = laws.get_section(conn, doc, pinpoint)
    if not section:
        raise NotFound(f"No section '{pinpoint}' in '{slug}'")
    return envelope(section)


class AskRequest(BaseModel):
    question: str = Field(min_length=5, max_length=1000)


@app.post("/ask")
def post_ask(body: AskRequest, conn: Conn, ai: AI, user: User, background: BackgroundTasks, connect: Connect):
    """Sources right away; the draft is written in the background, stored pending_review, never returned here."""
    question = body.question.strip()
    with tracing.observe("ask", input={"question": question}, metadata={"role": user["role"]}) as root:
        t0 = time.perf_counter()
        with tracing.observe("embed_query"):
            query_vector = ai.embed_query(question)
        with tracing.observe("retrieve", input={"question": question}) as span:
            # Fused candidates now (fast); the reranker orders them in the background, before drafting.
            candidates = ask.retrieve(conn, question, query_vector, top_k=RERANK_CANDIDATES)
            case_candidates = ask.retrieve(conn, question, query_vector, top_k=RERANK_CANDIDATES, kinds=["decision"])
            pages = ask.retrieve_web(conn, question, query_vector)
            hits = candidates[:ask.TOP_K] + pages + case_candidates[:ask.CASE_K]
            span.update(output=[{"chunk_id": h.chunk_id, "citation": h.source["citation"]["text"], "rrf": h.score,
                                 "distance": h.distance} for h in hits])
        timings = {"sources": round((time.perf_counter() - t0) * 1000)}
        trace_id = tracing.current_trace_id()
        with tracing.observe("store"):
            answer_id = ask.create_pending(conn, question, user["id"], hits, timings, trace_id)
        root.update(output={"answer_id": answer_id, "status": "drafting"}, metadata={"timings_ms": timings})
    background.add_task(draft_answer, connect, answer_id, question, candidates, ai.generate, trace_id,
                        getattr(ai, "rerank", None), case_candidates, pages)
    log.info("ask %s: sources in %s ms, drafting in background", answer_id, timings["sources"])
    best = min((h.distance for h in candidates if h.distance is not None), default=None)
    library_match = best is not None and best <= ask.GATE_MAX_DISTANCE  # False → the UI offers the web fallback
    return envelope({"answer_id": answer_id, "status": "pending_review", "sources": [h.source for h in hits]},
                    meta={"timings_ms": timings, "library_match": library_match})


@app.post("/ask/web")
def post_ask_web(body: AskRequest, conn: Conn, ai: AI, user: User, background: BackgroundTasks, connect: Connect):
    """Opt-in web fallback: a labelled draft from Google Search grounding, reviewed like any answer."""
    question = body.question.strip()
    with tracing.observe("ask_web", input={"question": question}) as root:
        answer_id = ask.create_pending(conn, question, user["id"], [], {"sources": 0}, tracing.current_trace_id())
        conn.execute("UPDATE answers SET flags = flags || '{\"web_fallback\": true}'::jsonb WHERE id = %s", (answer_id,))
        root.update(output={"answer_id": answer_id})
    background.add_task(draft_web_answer, connect, answer_id, question, ai.search_web)
    return envelope({"answer_id": answer_id, "status": "pending_review", "sources": []})


def draft_web_answer(connect, answer_id: int, question: str, search_web) -> None:
    import json

    with tracing.observe("draft_web", input={"answer_id": answer_id}) as span, connect() as conn:
        try:
            text, sources = search_web(question)
            status = "web" if sources else "not_found"
            conn.execute("UPDATE answers SET draft_markdown = %s, flags = flags || %s::jsonb WHERE id = %s",
                         (web_fallback.compose_web_draft(text, sources),
                          json.dumps({"status": status, "web_sources": sources}), answer_id))
            span.update(output={"status": status, "sources": len(sources)})
        except Exception as e:
            log.exception("web fallback for answer %s failed", answer_id)
            ask.fail_draft(conn, answer_id, f"{type(e).__name__}: {e}")


def draft_answer(connect, answer_id: int, question: str, candidates: list, generate, trace_id: str | None,
                 rerank=None, case_candidates: list | None = None, pages: list | None = None) -> None:
    """Background: rerank the candidates, generate + verify the draft, store it (or flag the failure for review)."""
    t0 = time.perf_counter()
    context = {"trace_context": {"trace_id": trace_id}} if trace_id else {}
    with tracing.observe("draft", input={"answer_id": answer_id}, **context) as span, connect() as conn:
        try:
            hits = rerank(question, candidates, ask.TOP_K) if rerank else candidates[:ask.TOP_K]
            hits += pages or []
            cases = case_candidates or []
            hits += rerank(question, cases, ask.CASE_K) if rerank and cases else cases[:ask.CASE_K]
            result = ask.run_ask(question, hits, generate, refine=lambda claims: ask.pinpoint_claims(conn, claims),
                                 library_titles=ask.library_titles(conn))
            ask.complete_draft(conn, answer_id, result, round((time.perf_counter() - t0) * 1000), hits)
            span.update(output={"status": result.status, "claims": len(result.claims), "dropped": len(result.dropped)})
            log.info("answer %s drafted: %s in %d ms", answer_id, result.status, (time.perf_counter() - t0) * 1000)
        except Exception as e:  # never lose the answer row: flag it for the reviewer
            log.exception("drafting answer %s failed", answer_id)
            ask.fail_draft(conn, answer_id, f"{type(e).__name__}: {e}")
            span.update(level="ERROR", status_message=str(e)[:200])


class ReviewRequest(BaseModel):
    decision: Literal["approve", "edit", "reject"]
    final_markdown: str | None = Field(default=None, max_length=20_000)
    note: str | None = Field(default=None, max_length=2_000)
    reason: Literal["wrong_law", "missing_authority", "unsupported_claim", "out_of_scope",
                    "legal_advice"] | None = None

    @model_validator(mode="after")
    def required_fields(self):
        if self.decision == "edit" and not ((self.final_markdown or "").strip() and (self.note or "").strip()):
            raise ValueError("edit needs final_markdown and a note")
        if self.decision == "reject" and not self.reason:
            raise ValueError("reject needs a reason")
        return self


@app.get("/review/queue")
def review_queue(conn: Conn, _: Reviewer):
    items = review.queue(conn)
    return envelope(items, meta={"total": len(items)})


@app.post("/answers/{answer_id}/review")
def review_answer(answer_id: int, body: ReviewRequest, conn: Conn, reviewer: Reviewer):
    status = review.decide(conn, answer_id, reviewer["id"], body.decision, body.final_markdown, body.note, body.reason)
    if status is None:
        drafting = review.drafting(conn, answer_id)
        if drafting is None:
            raise NotFound(f"No answer {answer_id}")
        if drafting:
            raise HTTPException(status_code=409, detail=f"Answer {answer_id} is still drafting; try again shortly")
        raise HTTPException(status_code=409, detail=f"Answer {answer_id} was already reviewed")
    try:
        review.log_decision(conn, answer_id)
    except Exception:  # the decision is saved; logging it must not turn success into an error
        log.exception("could not log review decision for answer %s", answer_id)
    log.info("answer %s %s by %s", answer_id, status, reviewer["name"])
    return envelope({"id": answer_id, "status": status})


@app.get("/answers/{answer_id}")
def get_answer(answer_id: int, conn: Conn, user: User):
    view = review.get_answer(conn, answer_id, user["role"])
    if not view:
        raise NotFound(f"No answer {answer_id}")
    return envelope(view)


@app.get("/suggest")
def get_suggest(q: Annotated[str, Query(min_length=2, max_length=200)], conn: Conn):
    """Typeahead: citations jump to a section; otherwise law titles and section headings (pg_trgm)."""
    return envelope(search.suggest(conn, q.strip()))


@app.get("/search")
def get_search(q: Annotated[str, Query(min_length=2, max_length=500)], conn: Conn, ai: AI):
    """Hybrid retrieval grouped by law. Question-shaped queries get meta.ask_this so the UI can offer 'Ask this'."""
    hits = search.search_hits(conn, q.strip(), ai.embed_query(q.strip()))
    groups = search.group_by_law(hits)
    return envelope(groups, meta={"total": len(hits), "ask_this": search.is_question(q)})


@app.get("/glossary")
def get_glossary(conn: Conn):
    items = laws.glossary(conn)
    return envelope(items, meta={"total": len(items)})


@app.get("/guides")
def get_guides(conn: Conn):
    return envelope(guides.list_guides(conn))


@app.get("/guides/{slug}")
def get_guide(slug: Slug, conn: Conn):
    guide = guides.get_guide(conn, slug)
    if not guide:
        raise NotFound(f"No guide '{slug}'")
    return envelope(guide)


@app.get("/cases/{slug}")
def get_case(slug: Slug, conn: Conn):
    case = cases.get_case(conn, slug)
    if not case:
        raise NotFound(f"No decision '{slug}'")
    return envelope(case)


class IngestRequest(BaseModel):
    url: str = Field(min_length=10, max_length=2000)
    in_scope: Literal[True]  # the reviewer confirms the page is about Ontario personal-injury law (#8)


@app.post("/ingest")
def post_ingest(body: IngestRequest, conn: Conn, queue: JobQueue, reviewer: Reviewer):
    """Reviewer adds an official web page they confirmed is in scope; a worker fetches, loads, chunks and embeds it."""
    url = body.url.strip()
    if web.site_of(url) is None:
        raise HTTPException(status_code=422, detail=f"Only https pages on {', '.join(web.ALLOWED_DOMAINS)} can be "
                                                    "added to the library")
    job_id = queue.enqueue(conn, "web_page", url, confirmed_by=reviewer["id"])
    log.info("ingest %s queued by %s: %s", job_id, reviewer["name"], url)
    return envelope(jobs.get_job(conn, job_id), status=202)


@app.get("/ingest/{job_id}")
def get_ingest(job_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")], conn: Conn):
    job = jobs.get_job(conn, job_id)
    if not job:
        raise NotFound(f"No ingest job '{job_id}'")
    return envelope(job)
