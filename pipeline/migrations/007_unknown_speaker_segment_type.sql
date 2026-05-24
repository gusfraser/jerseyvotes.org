-- Migration 007: unknown_speaker segment type
--
-- The audio pipeline (pyannote diarisation) sometimes produces speaker
-- labels we can't confidently map to either a candidate or a moderator.
-- Rather than drop those segments, store them with candidate_id=NULL
-- and segment_type='unknown_speaker'. A future manual review can
-- relabel them (via speaker_overrides in metadata.yaml + re-ingest), or
-- voice-fingerprinting can backfill them — but the underlying words are
-- preserved verbatim, never silently dropped.
--
-- The CHECK constraint on hustings_segments.segment_type was created by
-- migration 005 with five values; here we drop and re-add it to include
-- 'unknown_speaker'.
--
-- Idempotent: DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT.

BEGIN;

ALTER TABLE hustings_segments
    DROP CONSTRAINT IF EXISTS hustings_segments_segment_type_check;

ALTER TABLE hustings_segments
    ADD CONSTRAINT hustings_segments_segment_type_check CHECK (segment_type IN (
        'opening_speech',
        'question_answer',
        'closing_speech',
        'moderator',
        'audience_question',
        'unknown_speaker'
    ));

COMMIT;
