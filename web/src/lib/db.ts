import { neon } from "@neondatabase/serverless";

export const sql = neon(process.env.DATABASE_URL!);

export type Member = {
  member_id: number;
  canonical_name: string;
  display_name: string;
  first_vote_date: string;
  last_vote_date: string;
  is_currently_active: boolean;
  position_history: { position: string; count: number }[];
};

export type Proposition = {
  proposition_id: number;
  base_reference: string;
  year: number;
  number: number;
  source_url: string;
  title: string;
  topic_primary: string | null;
  topic_secondary: string | null;
  topic_tags: string[];
  plain_language_summary: string | null;
};

export type VoteDivision = {
  division_id: number;
  proposition_id: number;
  title: string;
  proposition_title: string;
  reference: string;
  date: string;
  division_stage: string;
  pour_count: number;
  contre_count: number;
  abstain_count: number;
  absent_count: number;
  total_eligible: number;
};

export type Vote = {
  division_id: number;
  member_id: number;
  vote: string;
  vote_category: string;
};

export const TOPICS = [
  "Government & Administration",
  "Constitutional & Electoral",
  "Finance & Taxation",
  "Employment & Social Security",
  "Transport & Infrastructure",
  "Planning & Environment",
  "Financial Services & Regulation",
  "Health & Wellbeing",
  "Property & Land",
  "Housing",
  "Justice & Policing",
  "Consumer & Commercial",
  "Children, Education & Families",
  "International & Trade",
  "Equality & Human Rights",
  "Agriculture, Fisheries & Rural",
] as const;
export type Topic = (typeof TOPICS)[number];

export const ELECTION_DATE = new Date("2026-06-07T00:00:00Z");

export function daysUntilElection(now: Date = new Date()): number {
  const ms = ELECTION_DATE.getTime() - now.getTime();
  return Math.max(0, Math.ceil(ms / (1000 * 60 * 60 * 24)));
}

// Parish / constituency constants live in `./parish` so client components
// can import them without dragging in the DB driver. Re-exported here for
// back-compat with existing `import { PARISHES, … } from "@/lib/db"` sites.
import { PARISHES, PARISH_DISTRICTS, type Parish } from "./parish";
export { PARISHES, PARISH_DISTRICTS, type Parish };

/**
 * Resolve a `constituency` query value (which may be a parish, a specific
 * district, or empty) into the SQL/filter shape we want:
 *   - constituencies: list of values to match `candidates.constituency` against
 *     (null = no filter)
 *   - includeSenators: whether to OR in role='Senator' (senators have no
 *     constituency, but the voter can still vote for them)
 *
 * Picking a parish expands to "everyone a voter there can vote for".
 * Picking a specific district stays literal (no Senator overlay) — that's
 * a power-user / explore-the-data view, not a personal-vote view.
 */
export function expandConstituency(value: string | null | undefined): {
  constituencies: string[] | null;
  includeSenators: boolean;
} {
  if (!value) return { constituencies: null, includeSenators: false };
  if ((PARISHES as readonly string[]).includes(value)) {
    return {
      constituencies: PARISH_DISTRICTS[value as Parish],
      includeSenators: true,
    };
  }
  return { constituencies: [value], includeSenators: false };
}

export type Candidate = {
  candidate_id: number;
  vote_je_slug: string;
  profile_url: string;
  full_name: string;
  canonical_name: string | null;
  role: string | null;
  constituency: string | null;
  party: string | null;
  photo_url: string | null;
  email: string | null;
  phone: string | null;
  manifesto_text: string | null;
  manifesto_word_count: number | null;
  incumbent_member_id: number | null;
  scrape_status: string;
  scraped_at: string;
  classified_at: string | null;
  correction_state: string;
  election_year: number;
};

export type CandidateTopic = {
  candidate_id: number;
  topic: Topic;
  salience: number;
  summary: string | null;
  source_quote: string | null;
};

export type CanonicalQuestion = {
  question_id: string;
  topic: Topic;
  statement: string;
  explainer: string | null;
  election_year: number;
  sort_order: number;
};

export type Stance = "agree" | "disagree" | "neutral" | "not_addressed";

export type CandidateStance = {
  candidate_id: number;
  question_id: string;
  stance: Stance;
  confidence: number;
  source_quote: string | null;
  corrected_stance: Stance | null;
};

// Corpus stats for the /ask "searching N manifestos and ~H hours of hustings"
// loader. Reflects what is actually searched (the rag_chunks index + hustings
// audio). Cached in-process so we don't query Neon on every render.
let _corpusCache: { value: { manifestos: number; hustingsHours: number }; at: number } | null = null;
const CORPUS_TTL_MS = 5 * 60_000;

export async function getCorpusStats(): Promise<{ manifestos: number; hustingsHours: number }> {
  const now = Date.now();
  if (_corpusCache && now - _corpusCache.at < CORPUS_TTL_MS) return _corpusCache.value;
  try {
    const rows = (await sql`
      SELECT
        (SELECT COUNT(DISTINCT candidate_id) FROM rag_chunks WHERE source_type = 'manifesto') AS manifestos,
        (SELECT COALESCE(SUM(duration_seconds), 0) FROM hustings_events) AS hustings_seconds
    `) as { manifestos: number; hustings_seconds: number }[];
    const r = rows[0];
    const value = {
      manifestos: Number(r?.manifestos ?? 0),
      hustingsHours: Math.round(Number(r?.hustings_seconds ?? 0) / 3600),
    };
    _corpusCache = { value, at: now };
    return value;
  } catch {
    return _corpusCache?.value ?? { manifestos: 0, hustingsHours: 0 };
  }
}
