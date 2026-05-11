-- Migration 001: Candidates section
--
-- Adds the four tables that back the /candidates section on jerseyvotes.org:
--   candidates             — one row per candidate scraped from vote.je
--   candidate_topics       — LLM-extracted topic salience per candidate
--   canonical_questions    — policy statements used by the matcher quiz
--   candidate_stances      — LLM-extracted agree/disagree per (candidate, question)
--
-- Idempotent: safe to re-run. Uses CREATE TABLE IF NOT EXISTS and explicit
-- DO blocks for indexes so this migration won't fail if partially applied.
-- Does NOT touch existing members / propositions / vote_divisions / votes tables.

BEGIN;

CREATE TABLE IF NOT EXISTS candidates (
    candidate_id SERIAL PRIMARY KEY,
    vote_je_slug TEXT UNIQUE NOT NULL,
    profile_url TEXT NOT NULL,
    full_name TEXT NOT NULL,
    canonical_name TEXT,
    role TEXT,
    constituency TEXT,
    party TEXT,
    photo_url TEXT,
    email TEXT,
    phone TEXT,
    manifesto_text TEXT,
    manifesto_word_count INTEGER,
    incumbent_member_id INTEGER REFERENCES members(member_id),
    scrape_status TEXT DEFAULT 'pending',
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    classified_at TIMESTAMPTZ,
    correction_token TEXT UNIQUE,
    correction_state TEXT DEFAULT 'pending',
    election_year INTEGER NOT NULL DEFAULT 2026
);

CREATE TABLE IF NOT EXISTS candidate_topics (
    candidate_id INTEGER REFERENCES candidates(candidate_id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    salience NUMERIC(3,2),
    summary TEXT,
    source_quote TEXT,
    PRIMARY KEY (candidate_id, topic)
);

CREATE TABLE IF NOT EXISTS canonical_questions (
    question_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    statement TEXT NOT NULL,
    explainer TEXT,
    election_year INTEGER NOT NULL DEFAULT 2026,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS candidate_stances (
    candidate_id INTEGER REFERENCES candidates(candidate_id) ON DELETE CASCADE,
    question_id TEXT REFERENCES canonical_questions(question_id) ON DELETE CASCADE,
    stance TEXT NOT NULL,
    confidence NUMERIC(3,2),
    source_quote TEXT,
    corrected_stance TEXT,
    corrected_at TIMESTAMPTZ,
    PRIMARY KEY (candidate_id, question_id)
);

-- Indexes (CREATE INDEX IF NOT EXISTS is supported in Postgres 9.5+)
CREATE INDEX IF NOT EXISTS idx_candidates_constituency  ON candidates(constituency);
CREATE INDEX IF NOT EXISTS idx_candidates_role           ON candidates(role);
CREATE INDEX IF NOT EXISTS idx_candidates_incumbent      ON candidates(incumbent_member_id);
CREATE INDEX IF NOT EXISTS idx_candidates_election_year  ON candidates(election_year);
CREATE INDEX IF NOT EXISTS idx_candidate_topics_topic    ON candidate_topics(topic);
CREATE INDEX IF NOT EXISTS idx_canonical_questions_topic ON canonical_questions(topic);

-- Populated lazily by the correction-form API route, but create up-front so
-- the column exists even before a submission lands.
ALTER TABLE candidates
    ADD COLUMN IF NOT EXISTS correction_notes JSONB DEFAULT '[]'::jsonb;

COMMIT;
