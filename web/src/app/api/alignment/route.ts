import { NextResponse } from "next/server";
import { sql } from "@/lib/db";

export async function GET() {
  // Get active members
  const members = await sql`
    SELECT member_id, canonical_name
    FROM members
    WHERE is_currently_active
    ORDER BY canonical_name
  `;

  // Get all votes for principles + third reading in current term
  const votes = await sql`
    SELECT v.member_id, v.division_id, v.vote
    FROM votes v
    JOIN vote_divisions vd ON v.division_id = vd.division_id
    WHERE v.vote IN ('Pour', 'Contre')
      AND vd.division_stage IN ('principles', 'third_reading')
      AND vd.date >= '2022-07-01'
      AND v.member_id IN (
        SELECT member_id FROM members WHERE is_currently_active
      )
    ORDER BY v.division_id
  `;

  // Build vote lookup: member_id -> { division_id -> vote }
  const memberVotes: Record<number, Record<number, number>> = {};
  for (const v of votes) {
    const mid = v.member_id as number;
    const did = v.division_id as number;
    const val = v.vote === "Pour" ? 1 : -1;
    if (!memberVotes[mid]) memberVotes[mid] = {};
    memberVotes[mid][did] = val;
  }

  // Compute pairwise agreement
  const names = members.map((m: Record<string, unknown>) => m.canonical_name as string);
  const ids = members.map((m: Record<string, unknown>) => m.member_id as number);
  const n = ids.length;

  const matrix: number[][] = Array.from({ length: n }, () =>
    Array(n).fill(0)
  );
  const sharedCounts: number[][] = Array.from({ length: n }, () =>
    Array(n).fill(0)
  );

  for (let i = 0; i < n; i++) {
    for (let j = i; j < n; j++) {
      const votesI = memberVotes[ids[i]] || {};
      const votesJ = memberVotes[ids[j]] || {};

      let agreed = 0;
      let shared = 0;

      for (const divId of Object.keys(votesI)) {
        if (divId in votesJ) {
          shared++;
          if (votesI[Number(divId)] === votesJ[Number(divId)]) {
            agreed++;
          }
        }
      }

      const pct = shared > 0 ? agreed / shared : 0;
      matrix[i][j] = pct;
      matrix[j][i] = pct;
      sharedCounts[i][j] = shared;
      sharedCounts[j][i] = shared;
    }
  }

  return NextResponse.json({ names, matrix, sharedCounts });
}
