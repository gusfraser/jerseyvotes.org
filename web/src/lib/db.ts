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
