"""HTTP API. Every response uses one envelope: {"data": ..., "error": {"code", "message"} | null, "meta": ... | null}.

Run: make api   (http://localhost:8000/docs)
"""
import logging
import os
import time
from functools import lru_cache
from typing import Annotated, Iterator, Literal

import psycopg
from fastapi import Depends, FastAPI, Header, Path, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from starlette.exceptions import HTTPException

from app import ask, laws, review
from ingest import vertex

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
SLUG = r"^[a-z0-9][a-z0-9.\-]*$"

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


@lru_cache(maxsize=1)
def get_ai() -> VertexAI:
    if os.environ.get("AI_FAKE") == "1":  # end-to-end UI tests only: deterministic, no Vertex calls
        from app.fake_ai import FakeAI

        log.warning("AI_FAKE=1: using the deterministic fake model (tests only)")
        return FakeAI(lambda: psycopg.connect(DATABASE_URL, autocommit=True), close_after=True)
    return VertexAI()


Conn = Annotated[psycopg.Connection, Depends(get_conn)]
AI = Annotated[VertexAI, Depends(get_ai)]


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
Slug = Annotated[str, Path(pattern=SLUG, max_length=100)]
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
def post_ask(body: AskRequest, conn: Conn, ai: AI, user: User):
    """Sources right away; the drafted answer is stored pending_review and never returned here."""
    question = body.question.strip()
    t0 = time.perf_counter()
    hits = ask.retrieve(conn, question, ai.embed_query(question))
    t_sources = time.perf_counter()
    result = ask.run_ask(question, hits, ai.generate, refine=lambda claims: ask.pinpoint_claims(conn, claims))
    timings = {"sources": round((t_sources - t0) * 1000), "total": round((time.perf_counter() - t0) * 1000)}
    answer_id = ask.store_answer(conn, question, user["id"], result, hits, timings)
    log.info("ask %s: %s, %d claims, %d dropped, %s", answer_id, result.status, len(result.claims),
             len(result.dropped), timings)
    return envelope({"answer_id": answer_id, "status": "pending_review", "sources": [h.source for h in hits]},
                    meta={"timings_ms": timings})


class ReviewRequest(BaseModel):
    decision: Literal["approve", "edit", "reject"]
    final_markdown: str | None = Field(default=None, max_length=20_000)
    note: str | None = Field(default=None, max_length=2_000)
    reason: Literal["wrong_law", "missing_authority", "unsupported_claim", "out_of_scope"] | None = None

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
        if not review.exists(conn, answer_id):
            raise NotFound(f"No answer {answer_id}")
        raise HTTPException(status_code=409, detail=f"Answer {answer_id} was already reviewed")
    log.info("answer %s %s by %s", answer_id, status, reviewer["name"])
    return envelope({"id": answer_id, "status": status})


@app.get("/answers/{answer_id}")
def get_answer(answer_id: int, conn: Conn, user: User):
    view = review.get_answer(conn, answer_id, user["role"])
    if not view:
        raise NotFound(f"No answer {answer_id}")
    return envelope(view)
