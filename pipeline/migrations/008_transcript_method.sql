-- Migration 008: transcript_method column on hustings_events
--
-- Distinguishes hand-cleaned transcripts (the user typed/cleaned them
-- by ear — broadcast-quality, fully attributed) from auto-pipeline
-- transcripts (yt-dlp + Whisper + pyannote — research-quality, may
-- have Whisper artefacts and partial speaker attribution).
--
-- Values:
--   'hand_cleaned'              — user-supplied transcript, gold standard
--   'auto_pipeline'             — produced by the audio pipeline, not yet reviewed
--   'auto_pipeline_reviewed'    — auto pipeline + a human pass via the
--                                 reviewer tooling (speaker_overrides applied,
--                                 obvious garbles cleaned, ready to publish)
--
-- The UI uses this to:
--   * Badge each event on /hustings, candidate pages, topic radar
--   * Adjust copy ("verbatim quote" wording is softer for auto events)
--   * Surface a "review this" affordance for auto_pipeline-only events
--
-- Defaults to 'auto_pipeline' for new rows — the ingest script flips
-- to 'hand_cleaned' when metadata.yaml has `transcript_method:
-- hand_cleaned` (or the legacy hand-cleaned events are seeded directly
-- in this migration).
--
-- Idempotent: ADD COLUMN IF NOT EXISTS + CHECK constraint dropped + readded.

BEGIN;

ALTER TABLE hustings_events
    ADD COLUMN IF NOT EXISTS transcript_method TEXT DEFAULT 'auto_pipeline';

ALTER TABLE hustings_events
    DROP CONSTRAINT IF EXISTS hustings_events_transcript_method_check;
ALTER TABLE hustings_events
    ADD CONSTRAINT hustings_events_transcript_method_check CHECK (transcript_method IN (
        'hand_cleaned',
        'auto_pipeline',
        'auto_pipeline_reviewed'
    ));

-- Seed the two events we know to be hand-cleaned.
UPDATE hustings_events
   SET transcript_method = 'hand_cleaned'
 WHERE slug IN ('st-helier-connetable-2026', 'st-helier-north-deputy-2026');

COMMIT;
