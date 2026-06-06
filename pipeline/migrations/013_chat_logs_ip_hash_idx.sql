-- Speeds up the per-IP hourly rate-limit count in /api/ask
-- (SELECT count(*) FROM chat_logs WHERE ip_hash = $1 AND created_at > now() - interval '1 hour').
CREATE INDEX IF NOT EXISTS idx_chat_logs_ip_hash_created
  ON chat_logs (ip_hash, created_at DESC);
