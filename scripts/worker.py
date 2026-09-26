"""Ingest worker: runs add-to-corpus jobs from the Redis stream (Phase 6.2). One process; Ctrl-C to stop.

Run: make worker   (uv run --env-file .env scripts/worker.py)
"""
import logging
import os
import socket
import sys
import time
from pathlib import Path

import psycopg
import redis

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.jobs import Queue  # noqa: E402
from ingest import web  # noqa: E402
from ingest.vertex import EMBED_MODEL, embedder, make_client  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
HOUSEKEEPING_EVERY_S = 30  # sweeper + reconciler
REDIS_SOCKET_TIMEOUT_S = 30  # must exceed the XREADGROUP block (5 s); redis-py 8 defaults to 5 s
log = logging.getLogger("worker")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    consumer = f"{socket.gethostname()}-{os.getpid()}"
    queue = Queue(redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=REDIS_SOCKET_TIMEOUT_S))
    queue.ensure_group()
    if os.environ.get("AI_FAKE") == "1":  # e2e: deterministic vectors, no Vertex
        embed, model = (lambda text: [0.01] * 1536), "fake-embed"
    else:
        embed, model = embedder(make_client()), EMBED_MODEL
    throttle = web.Throttle()

    def run(job, set_stage):
        return web.ingest_web(conn, job, set_stage, ROOT, throttle, embed, model)

    last_housekeeping = 0.0
    log.info("worker %s listening on stream %s", consumer, queue.stream)
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        while True:
            try:
                last_housekeeping = step(queue, conn, consumer, run, last_housekeeping)
            except redis.RedisError as e:  # Redis restarting: Postgres keeps the jobs; the reconciler re-adds them
                log.warning("redis unavailable (%s); retrying in 5 s", e)
                time.sleep(5)


def step(queue: Queue, conn, consumer: str, run, last_housekeeping: float) -> float:
    deliveries = []
    if time.monotonic() - last_housekeeping > HOUSEKEEPING_EVERY_S:
        queue.ensure_group()  # recreated if Redis lost the stream
        deliveries += queue.sweep(consumer)
        redispatched = queue.reconcile(conn)
        if redispatched:
            log.info("reconciler re-dispatched %s", redispatched)
        last_housekeeping = time.monotonic()
    deliveries += queue.claim(consumer)
    for entry, job_id in deliveries:
        log.info("job %s: start", job_id)
        queue.process(conn, entry, job_id, run)
        row = conn.execute("SELECT status, stage, error FROM ingest_jobs WHERE id = %s", (job_id,)).fetchone()
        log.info("job %s: %s", job_id, row)
    return last_housekeeping

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
