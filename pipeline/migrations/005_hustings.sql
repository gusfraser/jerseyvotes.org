-- Migration 005: Hustings transcripts
--
-- Vote.je publishes hustings (candidate panel) videos on its YouTube channel.
-- This migration adds tables for storing the diarised transcripts and the
-- per-segment topic tags. Hustings are a separate "spoken record" channel,
-- displayed on candidate pages but NEVER blended into candidate_topics or
-- candidate_stances — that's the structural guarantee that audience-chosen
-- questions cannot bias the matcher quiz.
--
-- Three tables:
--   hustings_events           — one row per video (constituency, role, date, URL)
--   hustings_segments         — one row per speech segment (speaker, text, time)
--   hustings_segment_topics   — one row per (segment, topic) — LLM-extracted
--
-- ON DELETE CASCADE from candidate_id so opting out or deleting a candidate
-- cleanly removes their hustings segments and downstream topic tags.
--
-- A CHECK constraint on transcript_source_url mirrors the methodology
-- invariant from migration 004 (manifesto_text_must_have_source_url): every
-- stored hustings text must point to a public URL anyone can verify against.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.

BEGIN;

CREATE TABLE IF NOT EXISTS hustings_events (
    event_id SERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    role TEXT,                         -- 'Deputy' / 'Connétable' / 'Senator'
    constituency TEXT,                 -- parish or district (NULL for island-wide)
    election_year INTEGER NOT NULL DEFAULT 2026,
    event_date DATE,
    youtube_url TEXT,
    transcript_source_url TEXT NOT NULL,   -- public URL where the transcript file can be audited (usually the GitHub blob URL)
    source_markdown_path TEXT,             -- relative path in the repo (for debugging)
    notes TEXT,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT hustings_events_transcript_url_nonempty CHECK (length(transcript_source_url) > 0)
);

CREATE TABLE IF NOT EXISTS hustings_segments (
    segment_id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES hustings_events(event_id) ON DELETE CASCADE,
    candidate_id INTEGER REFERENCES candidates(candidate_id) ON DELETE CASCADE,  -- NULL for moderator/audience segments
    speaker_name_raw TEXT NOT NULL,    -- the literal string from the transcript ("Steve Ahier", "Moderator", "Allison Marshall")
    segment_type TEXT NOT NULL CHECK (segment_type IN (
        'opening_speech',
        'question_answer',
        'closing_speech',
        'moderator',
        'audience_question'
    )),
    question_index INTEGER,            -- position of the question within the event (1-based); NULL for non-Q&A segments
    question_summary TEXT,             -- the question being answered (denormalised here for ease of querying)
    questioner_name TEXT,              -- audience member's name, when surfaced
    timestamp_seconds INTEGER,         -- start offset into the YouTube video, when known
    text TEXT NOT NULL,                -- the verbatim words spoken
    position_in_event INTEGER NOT NULL -- monotonic order within the event for stable sorting
);

CREATE TABLE IF NOT EXISTS hustings_segment_topics (
    segment_id INTEGER NOT NULL REFERENCES hustings_segments(segment_id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    salience NUMERIC(3,2),
    summary TEXT,
    source_quote TEXT,
    PRIMARY KEY (segment_id, topic)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_hustings_events_constituency_role
    ON hustings_events(constituency, role);
CREATE INDEX IF NOT EXISTS idx_hustings_events_election_year
    ON hustings_events(election_year);

CREATE INDEX IF NOT EXISTS idx_hustings_segments_candidate
    ON hustings_segments(candidate_id);
CREATE INDEX IF NOT EXISTS idx_hustings_segments_event
    ON hustings_segments(event_id);
CREATE INDEX IF NOT EXISTS idx_hustings_segments_event_position
    ON hustings_segments(event_id, position_in_event);

CREATE INDEX IF NOT EXISTS idx_hustings_segment_topics_topic
    ON hustings_segment_topics(topic);

COMMIT;
