-- Migration 010: RAG chunk index (pgvector)
--
-- Backs the /ask chat + semantic search feature. One unified table holding
-- embeddable chunks from BOTH content channels we already store:
--   * manifestos  — candidates.enhanced_manifesto_text (preferred) or
--                   candidates.manifesto_text (vote.je), chunked to ~paragraphs
--   * hustings    — one chunk per hustings_segments row (already segment-sized)
--
-- Co-located with the source rows (same Neon DB) so retrieval joins straight to
-- candidates / hustings_events and every citation traces to a public URL.
--
-- Transparency invariant (mirrors migrations 004 + 005): every chunk MUST carry
-- a non-empty public source_url. The builder (build_rag_index.py) only ever
-- writes chunks for candidates with opted_out_at IS NULL; the query route also
-- re-filters opted-out candidates at read time (belt and suspenders).
--
-- Idempotent identity is source_key (deterministic per chunk slot), NOT a
-- composite of nullable FKs — so build_rag_index.py can UPSERT ON CONFLICT
-- (source_key) and skip re-embedding chunks whose content_hash is unchanged.
--
-- Embeddings: voyage-3.5-lite → vector(1024). If the provider/model changes,
-- the dimension here must change too, followed by a full re-embed.
--
-- Idempotent: CREATE EXTENSION/TABLE/INDEX IF NOT EXISTS.

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id          BIGSERIAL PRIMARY KEY,
    source_key        TEXT NOT NULL UNIQUE,    -- 'manifesto:<candidate_id>:<i>' / 'hustings:<segment_id>:<i>'
    source_type       TEXT NOT NULL CHECK (source_type IN ('manifesto', 'hustings')),

    -- Source rows (nullable: a manifesto chunk has no segment/event; a
    -- moderator/audience hustings chunk has no candidate). ON DELETE CASCADE so
    -- deleting a candidate/event/segment cleanly removes its chunks.
    candidate_id      INTEGER REFERENCES candidates(candidate_id)       ON DELETE CASCADE,
    event_id          INTEGER REFERENCES hustings_events(event_id)      ON DELETE CASCADE,
    segment_id        INTEGER REFERENCES hustings_segments(segment_id)  ON DELETE CASCADE,

    content           TEXT NOT NULL,           -- the verbatim chunk text that gets embedded
    content_hash      TEXT NOT NULL,           -- sha256 of content → skip re-embed when unchanged
    token_count       INTEGER,

    -- Denormalised citation metadata (avoids joins on the retrieval hot path).
    candidate_name    TEXT,
    candidate_slug    TEXT,
    role              TEXT,                     -- Deputy / Connétable / Senator
    constituency      TEXT,
    source_url        TEXT NOT NULL,            -- public, auditable (vote.je profile / enhanced source / hustings transcript)
    source_label      TEXT,                     -- vote_je / enhanced:<label> / hustings:<event-slug>
    youtube_url       TEXT,                     -- hustings only → deep-link target
    timestamp_seconds INTEGER,                  -- hustings only → offset into the video
    segment_type      TEXT,                     -- hustings only (opening_speech/question_answer/closing_speech/...)
    topic_tags        TEXT[] DEFAULT '{}',      -- from candidate_topics / hustings_segment_topics

    embedding         vector(1024),             -- voyage-3.5-lite
    fts               tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,

    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT rag_chunks_source_url_nonempty CHECK (length(source_url) > 0)
);

-- Approximate-nearest-neighbour index for cosine similarity (Voyage vectors are
-- normalised; <=> with vector_cosine_ops is the right operator). HNSW handles
-- the small corpus comfortably and stays fast as it grows.
CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding
    ON rag_chunks USING hnsw (embedding vector_cosine_ops);

-- Keyword index — not used by v1 (semantic only) but free to maintain and lets
-- us add hybrid FTS ranking later with no re-index.
CREATE INDEX IF NOT EXISTS idx_rag_chunks_fts
    ON rag_chunks USING gin (fts);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_candidate    ON rag_chunks(candidate_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_event        ON rag_chunks(event_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_source_type  ON rag_chunks(source_type);

COMMIT;
