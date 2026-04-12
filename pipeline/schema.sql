-- AgenticGov Database Schema

DROP TABLE IF EXISTS votes CASCADE;
DROP TABLE IF EXISTS vote_divisions CASCADE;
DROP TABLE IF EXISTS propositions CASCADE;
DROP TABLE IF EXISTS members CASCADE;

-- Members table: all 158 unique politicians across 22 years
CREATE TABLE members (
    member_id SERIAL PRIMARY KEY,
    canonical_name TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    first_vote_date TIMESTAMPTZ,
    last_vote_date TIMESTAMPTZ,
    is_currently_active BOOLEAN DEFAULT FALSE,
    position_history JSONB DEFAULT '[]'
);

-- Propositions table: ~2,261 unique base propositions (P.XX/YYYY)
CREATE TABLE propositions (
    proposition_id SERIAL PRIMARY KEY,
    base_reference TEXT UNIQUE NOT NULL,   -- e.g. "P.57/2026"
    year INTEGER NOT NULL,
    number INTEGER NOT NULL,
    source_url TEXT,                        -- generated statesassembly.je URL
    title TEXT,                             -- most representative title
    topic_primary TEXT,                     -- LLM-classified category
    topic_secondary TEXT,                   -- optional second category
    topic_tags TEXT[] DEFAULT '{}',         -- fine-grained tags
    plain_language_summary TEXT             -- LLM-generated summary
);

-- Vote divisions table: 5,423 individual recorded votes (divisions)
CREATE TABLE vote_divisions (
    division_id INTEGER PRIMARY KEY,       -- the ID from CSV
    proposition_id INTEGER REFERENCES propositions(proposition_id),
    title TEXT,                             -- the Title column (division-level label)
    proposition_title TEXT,                 -- full PropositionTitle from CSV
    reference TEXT NOT NULL,                -- full reference incl amendments
    date TIMESTAMPTZ NOT NULL,
    division_stage TEXT,                    -- principles/third_reading/articles/amendment/paragraph/regulations/procedural/other
    amendment_number INTEGER,
    is_reissue BOOLEAN DEFAULT FALSE,
    pour_count INTEGER DEFAULT 0,
    contre_count INTEGER DEFAULT 0,
    abstain_count INTEGER DEFAULT 0,
    absent_count INTEGER DEFAULT 0,
    total_eligible INTEGER DEFAULT 0
);

-- Votes table: ~275K individual member votes
CREATE TABLE votes (
    division_id INTEGER REFERENCES vote_divisions(division_id),
    member_id INTEGER REFERENCES members(member_id),
    vote TEXT NOT NULL,                     -- original vote text (Pour, Contre, etc.)
    vote_category TEXT NOT NULL,            -- active_vote / excused_absence / unexcused_absence
    PRIMARY KEY (division_id, member_id)
);

-- Indexes for common query patterns
CREATE INDEX idx_votes_member ON votes(member_id);
CREATE INDEX idx_votes_division ON votes(division_id);
CREATE INDEX idx_votes_category ON votes(vote_category);
CREATE INDEX idx_divisions_date ON vote_divisions(date);
CREATE INDEX idx_divisions_stage ON vote_divisions(division_stage);
CREATE INDEX idx_divisions_proposition ON vote_divisions(proposition_id);
CREATE INDEX idx_propositions_year ON propositions(year);
CREATE INDEX idx_propositions_topic ON propositions(topic_primary);
CREATE INDEX idx_members_active ON members(is_currently_active);
