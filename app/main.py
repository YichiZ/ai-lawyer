"""HTTP API. Every response uses one envelope: {"data": ..., "error": {"code", "message"} | null, "meta": ... | null}.

Run: make api   (http://localhost:8000/docs)
"""
import logging
import os
from typing import Annotated, Iterator

import psycopg
from fastapi import Depends, FastAPI, Path, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app import laws

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
SLUG = r"^[a-z0-9][a-z0-9.\-]*$"

log = logging.getLogger("app")
app = FastAPI(title="Ontario Injury Law Guide API")


def get_conn() -> Iterator[psycopg.Connection]:
    # ponytail: one connection per request; add psycopg_pool when concurrency matters.
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        yield conn


Conn = Annotated[psycopg.Connection, Depends(get_conn)]
Slug = Annotated[str, Path(pattern=SLUG, max_length=100)]
Pinpoint = Annotated[str, Path(pattern=SLUG, max_length=100)]


def envelope(data=None, error=None, meta=None, status=200) -> JSONResponse:
    return JSONResponse(jsonable_encoder({"data": data, "error": error, "meta": meta}), status_code=status)


class NotFound(HTTPException):
    def __init__(self, message: str):
        super().__init__(status_code=404, detail=message)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    code = "not_found" if exc.status_code == 404 else "http_error"
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
