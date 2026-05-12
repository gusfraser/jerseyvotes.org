-- Migration 002: Enhanced (web-sourced) manifestos
--
-- vote.je has truncated platform text for many candidates. This migration adds
-- per-candidate columns to store a fuller manifesto sourced from the open web
-- (the candidate's personal site, party page, public Facebook post, etc.).
-- The original vote.je text in candidates.manifesto_text is preserved.
--
-- Populated by pipeline/find_enhanced_manifestos.py. Consumed by
-- classify_candidates.py via COALESCE(enhanced_manifesto_text, manifesto_text).
--
-- Idempotent: ADD COLUMN IF NOT EXISTS.

BEGIN;

ALTER TABLE candidates
    ADD COLUMN IF NOT EXISTS enhanced_manifesto_text TEXT,
    ADD COLUMN IF NOT EXISTS enhanced_manifesto_source_url TEXT,
    ADD COLUMN IF NOT EXISTS enhanced_manifesto_source_label TEXT,
    ADD COLUMN IF NOT EXISTS enhanced_manifesto_word_count INTEGER,
    ADD COLUMN IF NOT EXISTS enhanced_manifesto_fetched_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS enhanced_manifesto_status TEXT DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS enhanced_manifesto_notes TEXT;

CREATE INDEX IF NOT EXISTS idx_candidates_enhanced_status
    ON candidates(enhanced_manifesto_status);

COMMIT;
