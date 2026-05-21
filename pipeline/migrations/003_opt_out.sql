-- Migration 003: Candidate self-opt-out
--
-- Candidates can remove themselves from public display via their
-- token-gated review page at /candidates/correction/<token>. We soft-delete
-- (set opted_out_at = NOW()) rather than DELETE the row so that:
--
--   * the audit trail (manifesto, extracted topics/stances, prior corrections)
--     is preserved for the methodology's transparency claim;
--   * a candidate who changes their mind can be re-instated by setting the
--     column back to NULL — no re-scrape needed;
--   * foreign keys from candidate_topics / candidate_stances stay intact.
--
-- All public-facing queries must filter `opted_out_at IS NULL`. The scrape
-- upsert must preserve this column on conflict so re-scraping doesn't
-- accidentally reinstate an opted-out candidate.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.

BEGIN;

ALTER TABLE candidates
    ADD COLUMN IF NOT EXISTS opted_out_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_candidates_opted_out
    ON candidates(opted_out_at)
    WHERE opted_out_at IS NULL;

COMMIT;
