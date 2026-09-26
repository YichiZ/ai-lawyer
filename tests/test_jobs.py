import uuid

import pytest
import redis

from app import jobs


@pytest.fixture
def r():
    client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    stream = f"test-ingest-{uuid.uuid4().hex[:8]}"
    q = jobs.Queue(client, stream=stream, group="workers")
    q.ensure_group()
    yield q
    client.delete(stream, f"{stream}:dead")


def test_enqueue_is_idempotent_per_url(conn, r):
    a = r.enqueue(conn, "web_page", "https://www.ontario.ca/page/x")
    b = r.enqueue(conn, "web_page", "https://www.ontario.ca/page/x")
    assert a == b and conn.execute("SELECT count(*) FROM ingest_jobs WHERE id = %s", (a,)).fetchone()[0] == 1
    assert r.redis.xlen(r.stream) == 1  # only the first enqueue dispatches


def test_process_success_marks_done_and_acks(conn, r):
    jid = r.enqueue(conn, "web_page", "https://www.ontario.ca/page/ok")
    [(entry, job_id)] = r.claim("w1", block_ms=100)
    r.process(conn, entry, job_id, lambda job, stage: "ontario-page-ok")
    status, slug = conn.execute("SELECT status, document_slug FROM ingest_jobs WHERE id = %s", (jid,)).fetchone()
    assert (status, slug) == ("done", "ontario-page-ok")
    assert r.redis.xpending(r.stream, r.group)["pending"] == 0


def test_failure_backs_off_then_dead_letters_after_three(conn, r):
    jid = r.enqueue(conn, "web_page", "https://www.ontario.ca/page/bad")

    def boom(job, stage):
        stage("fetch")
        raise RuntimeError("503")

    delays = []
    for attempt in range(3):
        [(entry, job_id)] = r.claim("w1", block_ms=100) if attempt == 0 else [(r.redis.xadd(r.stream, {"job": jid}), jid)]
        r.process(conn, entry, job_id, boom)
        row = conn.execute("SELECT status, attempts, stage, error, next_attempt_at > now() FROM ingest_jobs WHERE id = %s", (jid,)).fetchone()
        delays.append(row)
    assert delays[0][:2] == ("queued", 1) and delays[0][4] is True  # backed off
    assert delays[2][:2] == ("dead", 3) and delays[2][2] == "fetch" and "503" in delays[2][3]
    assert r.redis.xlen(f"{r.stream}:dead") == 1


def test_reconciler_readds_jobs_redis_lost(conn, r):
    jid = r.enqueue(conn, "web_page", "https://www.ontario.ca/page/lost")
    r.redis.delete(r.stream)  # Redis lost the entry (flush / crash)
    r.ensure_group()
    conn.execute("UPDATE ingest_jobs SET updated_at = now() - interval '10 minutes' WHERE id = %s", (jid,))
    assert r.reconcile(conn) == [jid]
    [(entry, job_id)] = r.claim("w1", block_ms=100)
    assert job_id == jid


def test_sweeper_reclaims_entries_from_a_dead_worker(conn, r):
    jid = r.enqueue(conn, "web_page", "https://www.ontario.ca/page/stuck")
    r.claim("dead-worker", block_ms=100)  # claimed, never acked
    reclaimed = r.sweep("w2", min_idle_ms=0)
    assert [job for _, job in reclaimed] == [jid]


def test_already_done_job_is_skipped(conn, r):
    jid = r.enqueue(conn, "web_page", "https://www.ontario.ca/page/twice")
    [(entry, job_id)] = r.claim("w1", block_ms=100)
    r.process(conn, entry, job_id, lambda job, stage: "slug")
    calls = []
    r.process(conn, r.redis.xadd(r.stream, {"job": jid}), jid, lambda job, stage: calls.append(1) or "slug")
    assert calls == []  # duplicate delivery of a finished job does nothing


def test_backed_off_retry_is_dispatched_once_when_due(conn, r):
    jid = r.enqueue(conn, "web_page", "https://www.ontario.ca/page/retry")
    [(entry, job_id)] = r.claim("w1", block_ms=100)
    r.process(conn, entry, job_id, lambda job, stage: (_ for _ in ()).throw(RuntimeError("x")))
    assert r.reconcile(conn) == []  # still backing off
    conn.execute("UPDATE ingest_jobs SET next_attempt_at = now() - interval '1 second', "
                 "updated_at = now() - interval '2 seconds' WHERE id = %s", (jid,))
    assert r.reconcile(conn) == [jid]
    assert r.reconcile(conn) == []  # not re-dispatched on the next tick


def test_in_flight_job_is_not_run_twice(conn, r):
    jid = r.enqueue(conn, "web_page", "https://www.ontario.ca/page/inflight")
    conn.execute("UPDATE ingest_jobs SET status = 'running' WHERE id = %s", (jid,))
    calls = []
    r.process(conn, r.redis.xadd(r.stream, {"job": jid}), jid, lambda job, stage: calls.append(1) or "s")
    assert calls == []
