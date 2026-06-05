-- Migration 012: Feature flags (chat kill switch)
--
-- The whole /ask chat + semantic search surface sits behind a flag so it can be
-- turned off instantly if it misbehaves — important for an unproven AI feature
-- going live days before an election.
--
-- Toggle is instant, no redeploy:
--   UPDATE feature_flags SET enabled = TRUE,  updated_at = NOW() WHERE flag = 'chat';  -- turn ON
--   UPDATE feature_flags SET enabled = FALSE, updated_at = NOW() WHERE flag = 'chat';  -- kill
--
-- Seeded DISABLED on purpose: nothing goes live until it's enabled after
-- end-to-end verification. The env var CHAT_ENABLED=false is a separate
-- deploy-time hard-off that overrides this row (see web/src/lib/flags.ts).
--
-- ON CONFLICT DO NOTHING so re-running the migration never flips an
-- already-enabled flag back off.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + ON CONFLICT DO NOTHING.

BEGIN;

CREATE TABLE IF NOT EXISTS feature_flags (
    flag         TEXT PRIMARY KEY,
    enabled      BOOLEAN NOT NULL DEFAULT FALSE,
    description  TEXT,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO feature_flags (flag, enabled, description)
VALUES ('chat', FALSE, 'Master switch for the /ask chat + semantic search feature')
ON CONFLICT (flag) DO NOTHING;

COMMIT;
