"""Ingest job queue (docs/design.md → Job queue): Redis Streams dispatch, Postgres `ingest_jobs` the durable record.

Enqueue writes the row, then XADDs the job id. Workers XREADGROUP, run the job, update the row and XACK. Failures back
off (1, 4, 16 min) and are re-dispatched by the reconciler; the third failure marks the row dead and copies the id to
`<stream>:dead`. The sweeper XAUTOCLAIMs entries a crashed worker left pending; the reconciler re-adds queued rows
that Redis lost. Redis may lose anything — Postgres decides what runs.
"""
import hashlib
from typing import Callable

import psycopg
from psycopg.rows import dict_row
import redis

MAX_ATTEMPTS = 3
BACKOFF_MINUTES = (1, 4, 16)
STALE = "5 minutes"  # a queued/running row untouched this long is re-dispatched by the reconciler
STREAM_MAXLEN = 100_000  # approximate cap; Postgres holds the backlog, the stream only dispatches


def job_id(kind: str, url: str) -> str:
    return hashlib.sha256(f"{kind}\n{url}".encode()).hexdigest()[:32]


class Queue:
    def __init__(self, client: redis.Redis, stream: str = "ingest", group: str = "workers"):
        self.redis, self.stream, self.group = client, stream, group

    def ensure_group(self) -> None:
        try:
            self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def _dispatch(self, jid: str) -> None:
        self.redis.xadd(self.stream, {"job": jid}, maxlen=STREAM_MAXLEN, approximate=True)

    def enqueue(self, conn: psycopg.Connection, kind: str, url: str) -> str:
        """Idempotent: the same (kind, url) is one job; only a new (or dead, retried) row is dispatched."""
        jid = job_id(kind, url)
        with conn.transaction():
            row = conn.execute(
                """INSERT INTO ingest_jobs (id, kind, url) VALUES (%s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET status = 'queued', attempts = 0, error = NULL, stage = NULL,
                       next_attempt_at = now(), updated_at = now()
                     WHERE ingest_jobs.status = 'dead'
                   RETURNING id""",
                (jid, kind, url),
            ).fetchone()
        if row:
            self._dispatch(jid)
        return jid

    def claim(self, consumer: str, block_ms: int = 5000, count: int = 1) -> list[tuple[str, str]]:
        """[(entry id, job id)] newly delivered to this consumer."""
        resp = self.redis.xreadgroup(self.group, consumer, {self.stream: ">"}, count=count, block=block_ms)
        return [(eid, fields["job"]) for _, entries in resp or [] for eid, fields in entries]

    def sweep(self, consumer: str, min_idle_ms: int = 5 * 60_000) -> list[tuple[str, str]]:
        """Take over entries another (crashed) worker claimed but never acked."""
        _, entries, _ = self.redis.xautoclaim(self.stream, self.group, consumer, min_idle_time=min_idle_ms)
        return [(eid, fields["job"]) for eid, fields in entries if fields]

    def reconcile(self, conn: psycopg.Connection) -> list[str]:
        """Re-dispatch due queued rows (backed-off retries, or entries Redis lost) and stale running rows."""
        with conn.transaction():
            rows = conn.execute(
                f"""UPDATE ingest_jobs SET updated_at = now()
                    WHERE (status = 'queued' AND next_attempt_at <= now() AND updated_at < now() - interval '{STALE}')
                       OR (status = 'queued' AND attempts > 0 AND next_attempt_at <= now() AND updated_at < next_attempt_at)
                       OR (status = 'running' AND updated_at < now() - interval '{STALE}')
                    RETURNING id"""
            ).fetchall()
        for (jid,) in rows:
            self._dispatch(jid)
        return [jid for (jid,) in rows]

    def process(self, conn: psycopg.Connection, entry: str, jid: str,
                run: Callable[[dict, Callable[[str], None]], str]) -> None:
        """Run one delivery. `run(job, set_stage)` returns the loaded document's slug."""
        with conn.transaction():
            job = conn.execute(
                f"""UPDATE ingest_jobs SET status = 'running', updated_at = now()
                   WHERE id = %s AND (status = 'queued' OR (status = 'running' AND updated_at < now() - interval '{STALE}'))
                   RETURNING id, kind, url, attempts""",
                (jid,),
            ).fetchone()
        if job is None:  # done, dead, in flight elsewhere or unknown: a duplicate delivery
            self.redis.xack(self.stream, self.group, entry)
            return
        job = dict(zip(("id", "kind", "url", "attempts"), job))

        def set_stage(stage: str) -> None:
            with conn.transaction():
                conn.execute("UPDATE ingest_jobs SET stage = %s, updated_at = now() WHERE id = %s", (stage, jid))

        try:
            slug = run(job, set_stage)
        except Exception as e:  # any failure is recorded on the row, never lost
            self._fail(conn, job, f"{type(e).__name__}: {e}"[:500], permanent=getattr(e, "permanent", False))
        else:
            with conn.transaction():
                conn.execute("""UPDATE ingest_jobs SET status = 'done', stage = 'done', document_slug = %s,
                                error = NULL, updated_at = now() WHERE id = %s""", (slug, jid))
        self.redis.xack(self.stream, self.group, entry)

    def _fail(self, conn: psycopg.Connection, job: dict, error: str, permanent: bool = False) -> None:
        attempts = job["attempts"] + 1
        if attempts >= MAX_ATTEMPTS or permanent:  # permanent: e.g. a refused domain — retrying cannot help
            with conn.transaction():
                conn.execute("UPDATE ingest_jobs SET status = 'dead', attempts = %s, error = %s, updated_at = now() "
                             "WHERE id = %s", (attempts, error, job["id"]))
            self.redis.xadd(f"{self.stream}:dead", {"job": job["id"], "error": error})
            return
        with conn.transaction():
            conn.execute(
                """UPDATE ingest_jobs SET status = 'queued', attempts = %s, error = %s, updated_at = now(),
                       next_attempt_at = now() + make_interval(mins => %s) WHERE id = %s""",
                (attempts, error, BACKOFF_MINUTES[attempts - 1], job["id"]),
            )


def get_job(conn: psycopg.Connection, jid: str) -> dict | None:
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT id, kind, url, status, stage, attempts, error, document_slug, enqueued_at, updated_at"
        " FROM ingest_jobs WHERE id = %s", (jid,)).fetchone()
