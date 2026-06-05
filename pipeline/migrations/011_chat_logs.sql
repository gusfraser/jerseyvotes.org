-- Migration 011: Chat request/response audit log
--
-- Every call to /api/ask is persisted here — the requirement is to store all
-- requests and responses. One row per request, written on EVERY exit path:
--   answered | refused_off_topic | no_results | disabled | error
--
-- request_id correlates a row with its Logfire trace, so an operator can jump
-- from a logged answer to the full span timeline (gate → embed → retrieve →
-- synthesize) and back.
--
-- Privacy: store a salted hash of the caller IP, never the raw address
-- (consistent with the site's /privacy posture). citations holds the chunk ids
-- + source metadata actually used in the answer.
--
-- Idempotent: CREATE TABLE/INDEX IF NOT EXISTS.

BEGIN;

CREATE TABLE IF NOT EXISTS chat_logs (
    log_id           BIGSERIAL PRIMARY KEY,
    request_id       TEXT NOT NULL,             -- correlates with the Logfire trace
    created_at       TIMESTAMPTZ DEFAULT NOW(),

    question         TEXT NOT NULL,
    scope_type       TEXT,                      -- 'site' | 'candidate' | 'hustings'
    scope_ref        TEXT,                      -- candidate/event slug when scoped

    status           TEXT NOT NULL,             -- answered | refused_off_topic | no_results | disabled | error
    gate_on_topic    BOOLEAN,                   -- result of the on-topic classifier
    gate_reason      TEXT,

    answer           TEXT,                      -- full synthesized answer (accumulated server-side)
    citations        JSONB DEFAULT '[]',        -- [{chunk_id, source_type, candidate_slug, source_url, ...}]
    retrieval_count  INTEGER,                   -- chunks retrieved above threshold
    top_score        NUMERIC,                   -- best cosine similarity for this query

    model            TEXT,                      -- synthesis model id
    input_tokens     INTEGER,
    output_tokens    INTEGER,
    latency_ms       INTEGER,

    ip_hash          TEXT,                      -- salted hash, NOT the raw IP
    user_agent       TEXT,
    error            TEXT                       -- message when status = 'error'
);

CREATE INDEX IF NOT EXISTS idx_chat_logs_created ON chat_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_chat_logs_status  ON chat_logs(status);

COMMIT;
