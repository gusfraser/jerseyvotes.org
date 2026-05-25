-- Migration 009: enrich hustings_segments with YouTube-ASR splice + summary provenance
--
-- Two columns added to hustings_segments:
--
--   text_youtube_asr TEXT          -- verbatim audience-question text spliced
--                                     from youtube_captions.vtt, populated by
--                                     pipeline/splice_youtube_asr.py. NULL for
--                                     non-audience segments and for hand-cleaned
--                                     events. The display reads this in
--                                     preference to `text` for the "as captured"
--                                     disclosure on audience questions, because
--                                     YouTube's caption model handles distant
--                                     audience-mic speech materially better than
--                                     our Whisper+pyannote chain.
--
--   question_summary_source TEXT   -- 'verbatim' (default — question_summary is
--                                     the raw audience body from ingest) or
--                                     'llm_synthesised' (the value was written
--                                     by pipeline/summarise_hustings_questions.py
--                                     based on the audience text + first 2-3
--                                     candidate answers). The display uses this
--                                     to decide whether to render the "as
--                                     captured" disclosure (only useful when the
--                                     headline is a synthesised summary).
--
-- Idempotent: ADD COLUMN IF NOT EXISTS + CHECK constraint dropped + readded.

BEGIN;

ALTER TABLE hustings_segments
    ADD COLUMN IF NOT EXISTS text_youtube_asr TEXT;

ALTER TABLE hustings_segments
    ADD COLUMN IF NOT EXISTS question_summary_source TEXT DEFAULT 'verbatim';

ALTER TABLE hustings_segments
    DROP CONSTRAINT IF EXISTS hustings_segments_question_summary_source_check;
ALTER TABLE hustings_segments
    ADD CONSTRAINT hustings_segments_question_summary_source_check CHECK (
        question_summary_source IN ('verbatim', 'llm_synthesised')
    );

COMMIT;
