-- Hard-block list for the Ask feature. IP+user-agent combinations that hit
-- unrealistic request volumes are recorded here (by a stable, pseudonymous key)
-- and blocked until expires_at. Populated automatically by /api/ask; rows can
-- also be added/removed by hand to block or unblock an offender.
CREATE TABLE IF NOT EXISTS ask_blocks (
  block_key  text PRIMARY KEY,
  reason     text,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ask_blocks_expires ON ask_blocks (expires_at);
