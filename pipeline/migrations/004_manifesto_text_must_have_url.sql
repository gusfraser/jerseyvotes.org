-- Migration 004: Transparency invariant — every stored manifesto text
-- must point to a public source URL that anyone can verify against.
--
-- Two CHECK constraints, one per source:
--   * manifesto_text (vote.je-sourced) requires profile_url
--   * enhanced_manifesto_text (web-sourced) requires enhanced_manifesto_source_url
--
-- The candidate profile page already surfaces both links to readers; this
-- migration moves that promise from "current behaviour" to "DB-enforced
-- invariant" so a future code change cannot silently store untraceable text.
--
-- Idempotent: drops + re-adds the constraints (so re-running this migration
-- after the constraint definition is tightened just refreshes it).

BEGIN;

ALTER TABLE candidates DROP CONSTRAINT IF EXISTS manifesto_text_must_have_voteje_url;
ALTER TABLE candidates ADD CONSTRAINT manifesto_text_must_have_voteje_url CHECK (
    manifesto_text IS NULL
    OR length(manifesto_text) = 0
    OR (profile_url IS NOT NULL AND length(profile_url) > 0)
);

ALTER TABLE candidates DROP CONSTRAINT IF EXISTS enhanced_manifesto_text_must_have_source_url;
ALTER TABLE candidates ADD CONSTRAINT enhanced_manifesto_text_must_have_source_url CHECK (
    enhanced_manifesto_text IS NULL
    OR length(enhanced_manifesto_text) = 0
    OR (enhanced_manifesto_source_url IS NOT NULL AND length(enhanced_manifesto_source_url) > 0)
);

COMMIT;
