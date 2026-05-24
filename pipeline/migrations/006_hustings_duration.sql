-- Migration 006: Hustings event duration
--
-- Adds a duration_seconds column to hustings_events so the /hustings index
-- can show "K events covering N hours of audio" headline stats.
--
-- Populated from yt-dlp's video_metadata.json by ingest_hustings.py when
-- a `duration_seconds:` key is present in metadata.yaml. NULL when the
-- event was transcribed without an underlying audio recording on file.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS.

BEGIN;

ALTER TABLE hustings_events
    ADD COLUMN IF NOT EXISTS duration_seconds INTEGER;

COMMIT;
