# Phase 6 plan — web fallback, add-to-corpus, load test

Phase exit (from `docs/design.md`): web fallback (reviewed) + add-to-corpus; load test — **fallback labelled and
ingestible; p95 vs targets**.

Pre-approved (2026-09-26): web fetches from ontario.ca, canada.ca, ontariocourts.ca, scc-csc.ca and toronto.ca (excerpt
rule), robots.txt respected, ≤ 1 request/s per domain, never CanLII; `locust` (dev). Same loop and rules.

---

## 6.1 Web fallback (opt-in, reviewed)

**Accept**: when the grounding gate says "not found" (or the reviewer asks for it), a researcher can opt in to
"Search the web" — gemini-3.7-flash with Google Search grounding (low thinking; grounding chunks must be non-empty or
the answer is refused). Vertex redirect URLs are resolved to the real URL and title before storing. The draft is
labelled "From the web, not our law library", goes through the review queue like any answer (flag `web_fallback`,
risky-first), and lists its web sources with domains. Quote verification does not apply to web text; the reviewer
sees the flag and the sources instead.

**Tests**: redirect resolution (fake HTTP); refusal when no grounding chunks; label and flag stored; queue ordering.

## 6.2 Add to corpus

**Accept**: from a web-fallback answer, the reviewer can "Add source to library" for sources on the allowed domains
only: the fetch obeys robots.txt and ≤ 1 req/s, stores the file in `input/web/` with a manifest line (url, sha256,
licence note), parses HTML/PDF (pdftotext; toronto.ca stays excerpt-only), loads it as a document, chunks and embeds it
— through the Redis Streams job queue from the design (Postgres `ingest_jobs` as the durable record, `XADD` /
`XREADGROUP` / `XACK`, `XAUTOCLAIM` sweeper, reconciler, 3 retries then dead-letter). `GET /ingest/{job_id}` reports
status and stage. Non-allowed domains are refused with a clear message.

**Tests**: domain allow-list; robots.txt check; job state machine (queued → running → done / retry → dead);
reconciler re-adds lost jobs; idempotency by sha256; an end-to-end ingest of a small fixture page.

**Stop if** Redis is not wanted after all — the queue is the only new service (Redis 8 in Docker Compose, from the
design); confirm before adding it to `docker-compose.yml`.

## 6.3 Load test

**Accept**: `locust` scenario mixing section pages, search, suggest and `/ask` (fake model for load; one run with the
real model at low rate for draft latency); report p50/p95 for sources and drafts against the targets (< 2 s / < 8 s);
note the Vertex quota ceiling observed; recommendations (quota increase, connection pool) written up.

**Validate**: numbers table in `docs/iterations.md`; no errors under the target load; baseline unchanged.

---

**Phase exit**: web fallback labelled and reviewed · add-to-corpus ingests an allowed page end to end · load test
table recorded · final baseline and CI green.
