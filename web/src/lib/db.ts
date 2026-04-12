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
