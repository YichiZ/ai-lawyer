-- Phase 1 schema. Idempotent: safe to apply repeatedly (make db).
-- ponytail: IF NOT EXISTS only covers creation; add a migration tool when a column must change on live data.

SET client_min_messages = warning;  -- hide "already exists, skipping" notices on re-apply

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS documents (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sha256           text NOT NULL UNIQUE,
    kind             text NOT NULL CHECK (kind IN ('statute', 'regulation', 'bylaw', 'decision')),
    slug             text NOT NULL UNIQUE,
    title            text NOT NULL,
    short_name       text,
    neutral_citation text,
    court            text,
    jurisdiction     text NOT NULL DEFAULT 'ON',
    date             date,
    in_force_from    date,
    in_force_to      date,
    supersedes_id    bigint REFERENCES documents (id),
    url              text,
    source           text NOT NULL,
    upstream_license text,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sections (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id         bigint NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    parent_id           bigint REFERENCES sections (id) ON DELETE CASCADE,
    pinpoint            text NOT NULL,
    heading             text,
    text                text NOT NULL,
    plain_summary       text,
    summary_source_hash text,
    sort_order          integer NOT NULL,
    UNIQUE (document_id, pinpoint)
);

CREATE TABLE IF NOT EXISTS chunks (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id     bigint NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    section_ids     bigint[] NOT NULL DEFAULT '{}',
    pinpoint        text NOT NULL,
    text            text NOT NULL,
    text_sha256     text NOT NULL,  -- embedding cache key: unchanged text = no re-embed
    context         text,
    tsv             tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(context, '') || ' ' || text)) STORED,
    embedding       halfvec(1536),
    embedding_model text
);

CREATE TABLE IF NOT EXISTS users (
    id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL,
    role text NOT NULL CHECK (role IN ('researcher', 'reviewer'))
);

CREATE TABLE IF NOT EXISTS answers (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trace_id       text,
    asked_by       bigint REFERENCES users (id),
    question       text NOT NULL,
    draft_markdown text,
    claims         jsonb NOT NULL DEFAULT '[]',
    flags          jsonb NOT NULL DEFAULT '[]',
    status         text NOT NULL DEFAULT 'pending_review'
                   CHECK (status IN ('pending_review', 'approved', 'edited', 'rejected')),
    reviewed_by    bigint REFERENCES users (id),
    reviewed_at    timestamptz,
    review_reason  text,
    review_note    text,
    final_markdown text,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding halfvec_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_document ON chunks (document_id);
CREATE INDEX IF NOT EXISTS documents_title_trgm ON documents USING gin (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS sections_heading_trgm ON sections USING gin (heading gin_trgm_ops);
CREATE INDEX IF NOT EXISTS sections_document_order ON sections (document_id, sort_order);
CREATE INDEX IF NOT EXISTS documents_kind_court_date ON documents (kind, court, date);
CREATE INDEX IF NOT EXISTS answers_status_created ON answers (status, created_at);

-- 1.3: columns added after the first schema; ADD COLUMN IF NOT EXISTS keeps re-apply idempotent.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS citation text;
ALTER TABLE sections ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'section'
    CHECK (kind IN ('part', 'section', 'subsection'));

-- 1.5: 'excerpt' = source copyright forbids republishing (Toronto Municipal Code): UI shows excerpts + link only.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS reproduction text NOT NULL DEFAULT 'full'
    CHECK (reproduction IN ('full', 'excerpt'));

-- 1.9: two seeded demo users (no real auth; the role comes from the X-Demo-User header).
CREATE UNIQUE INDEX IF NOT EXISTS users_name_key ON users (name);
INSERT INTO users (name, role) VALUES ('Demo Researcher', 'researcher'), ('Demo Reviewer', 'reviewer')
    ON CONFLICT (name) DO NOTHING;

-- 3.5: LLM "situating" sentences per chunk (embedding input only; keyword tsv unchanged).
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS situating text;

-- 4.3: glossary (definitions written from the defining statutory text where one exists).
CREATE TABLE IF NOT EXISTS glossary_terms (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    term             text NOT NULL UNIQUE,
    plain_definition text NOT NULL,
    source_slug      text,
    source_pinpoint  text,
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- 4.4: topic guides. Each guide section is an ordinary answer, so it goes through the review queue.
CREATE TABLE IF NOT EXISTS guides (
    slug       text PRIMARY KEY,
    title      text NOT NULL,
    intro      text NOT NULL,
    sort_order integer NOT NULL
);
CREATE TABLE IF NOT EXISTS guide_sections (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guide_slug text NOT NULL REFERENCES guides (slug) ON DELETE CASCADE,
    heading    text NOT NULL,
    question   text NOT NULL,
    answer_id  bigint REFERENCES answers (id),
    sort_order integer NOT NULL,
    UNIQUE (guide_slug, heading)
);

-- 5.4: citation graph. A decision cites a decision (A2AJ lists; cited_document_id when it is in the corpus) or a
-- statute section (regex; cited_section_id when the pinpoint resolves).
CREATE TABLE IF NOT EXISTS citations (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    citing_document_id bigint NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    kind               text NOT NULL CHECK (kind IN ('case', 'statute')),
    cited_citation     text,
    cited_document_id  bigint REFERENCES documents (id) ON DELETE SET NULL,
    cited_slug         text,
    cited_pinpoint     text,
    cited_section_id   bigint REFERENCES sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS citations_citing ON citations (citing_document_id);
CREATE INDEX IF NOT EXISTS citations_cited_doc ON citations (cited_document_id);
CREATE INDEX IF NOT EXISTS citations_cited_section ON citations (cited_section_id);

-- 5.5: plain-language decision summaries (facts, outcome, why it matters).
ALTER TABLE documents ADD COLUMN IF NOT EXISTS plain_summary text;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS summary_source_hash text;

-- 6.2: durable job records (Redis Streams only dispatch; see docs/design.md → Job queue).
CREATE TABLE IF NOT EXISTS ingest_jobs (
    id              text PRIMARY KEY,               -- sha256 of kind + url: a duplicate enqueue is a no-op
    kind            text NOT NULL,
    url             text NOT NULL,
    status          text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'dead')),
    stage           text,
    attempts        integer NOT NULL DEFAULT 0,
    error           text,
    document_slug   text,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    enqueued_at     timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_kind_check;
ALTER TABLE documents ADD CONSTRAINT documents_kind_check CHECK (kind IN ('statute', 'regulation', 'bylaw', 'decision', 'web'));
