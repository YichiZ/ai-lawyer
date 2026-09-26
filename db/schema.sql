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
