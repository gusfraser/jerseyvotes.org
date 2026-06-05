import { sql } from "@/lib/db";

// Feature flags. v1 has exactly one: `chat` — the master switch for the /ask
// chat + semantic search surface.
//
// Resolution order:
//   1. CHAT_ENABLED env var (deploy-time hard override): "true"/"1"/"on" forces
//      ON, "false"/"0"/"off" forces OFF. Used to force-enable locally for
//      verification, or to kill the feature at the platform level.
//   2. feature_flags.chat row in Neon (instant toggle, no redeploy).
//   3. Default OFF — and we fail OFF on any error, so the failure mode is
//      "feature hidden", never "site broken".
//
// The DB read is cached in-process for a short TTL so we don't hit Neon on
// every render (the root layout calls this on each request to gate the nav).

const TTL_MS = 30_000;
let cache: { value: boolean; at: number } | null = null;

function envOverride(): boolean | null {
  const v = process.env.CHAT_ENABLED;
  if (v == null || v.trim() === "") return null;
  const s = v.trim().toLowerCase();
  if (["false", "0", "off", "no"].includes(s)) return false;
  if (["true", "1", "on", "yes"].includes(s)) return true;
  return null;
}

export async function isChatEnabled(): Promise<boolean> {
  const override = envOverride();
  if (override !== null) return override;

  const now = Date.now();
  if (cache && now - cache.at < TTL_MS) return cache.value;

  try {
    const rows = (await sql`
      SELECT enabled FROM feature_flags WHERE flag = 'chat' LIMIT 1
    `) as { enabled: boolean }[];
    const value = rows.length > 0 ? Boolean(rows[0].enabled) : false;
    cache = { value, at: now };
    return value;
  } catch {
    // Fail closed. If we have a recent cached value, keep using it; otherwise off.
    return cache?.value ?? false;
  }
}
