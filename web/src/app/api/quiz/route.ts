import { NextResponse } from "next/server";
import { sql } from "@/lib/db";

export async function GET() {
  // Select the most divisive Principles votes in the current term
  // Prefer Principles over Third Reading to avoid near-duplicate questions
  // Select genuinely divisive votes (>=25% minority) across principles,
  // third reading, and amendment stages for maximum topic diversity
  const candidates = await sql`
    SELECT vd.division_id, vd.proposition_title, vd.date::date as vote_date,
           vd.pour_count, vd.contre_count, vd.division_stage,
           p.topic_primary, p.plain_language_summary, p.extended_summary, p.base_reference, p.source_url,
           ABS(vd.pour_count::float / NULLIF(vd.pour_count + vd.contre_count, 0) - 0.5) as split_distance
    FROM vote_divisions vd
    JOIN propositions p ON vd.proposition_id = p.proposition_id
    WHERE vd.division_stage IN ('principles', 'third_reading', 'amendment')
      AND vd.date >= '2022-07-01'
      AND (vd.pour_count + vd.contre_count) >= 20
      AND LEAST(vd.pour_count, vd.contre_count)::float
          / NULLIF(vd.pour_count + vd.contre_count, 0) >= 0.25
      AND p.topic_primary IS NOT NULL
    ORDER BY split_distance ASC
    LIMIT 200
  `;

  // Select questions ensuring topic diversity and avoiding near-duplicate
  // titles from the same proposition (e.g., multiple budget amendments)
  const selected: typeof candidates = [];
  const topicCounts: Record<string, number> = {};
  const seenTitlePrefixes = new Set<string>();

  for (const c of candidates) {
    const topic = c.topic_primary as string;
    // Dedup: use base_reference to avoid multiple votes on the same proposition,
    // plus first 30 chars of title to catch related propositions (e.g., multiple
    // Senators reinstatement attempts across different sessions)
    const ref = c.base_reference as string;
    const titlePrefix = (c.proposition_title as string).slice(0, 30);

    if (seenTitlePrefixes.has(titlePrefix) || seenTitlePrefixes.has(ref)) continue;
    // Limit 4 per topic
    if ((topicCounts[topic] || 0) >= 4) continue;

    selected.push(c);
    topicCounts[topic] = (topicCounts[topic] || 0) + 1;
    seenTitlePrefixes.add(titlePrefix);
    seenTitlePrefixes.add(ref);

    if (selected.length >= 30) break;
  }

  const questions = selected.map((q) => ({
    divisionId: q.division_id,
    title: q.proposition_title,
    summary: q.plain_language_summary || null,
    extendedSummary: q.extended_summary || null,
    topic: q.topic_primary,
    reference: q.base_reference,
    sourceUrl: q.source_url,
    date: q.vote_date,
    pourCount: q.pour_count,
    contreCount: q.contre_count,
    passed: (q.pour_count as number) > (q.contre_count as number),
  }));

  return NextResponse.json({ questions });
}

export async function POST(request: Request) {
  const { answers } = await request.json();
  // answers: { divisionId: number, vote: 'pour' | 'contre' }[]

  if (!answers || !Array.isArray(answers) || answers.length === 0) {
    return NextResponse.json({ error: "No answers provided" }, { status: 400 });
  }

  const divisionIds = answers.map((a: { divisionId: number }) => a.divisionId);

  // Get all active member votes for these divisions
  const memberVotes = await sql`
    SELECT v.member_id, v.division_id, v.vote,
           m.canonical_name, m.display_name, m.position_history
    FROM votes v
    JOIN members m ON v.member_id = m.member_id
    WHERE v.division_id = ANY(${divisionIds})
      AND v.vote IN ('Pour', 'Contre')
      AND m.is_currently_active
  `;

  // Build user answer lookup
  const userVotes: Record<number, number> = {};
  for (const a of answers) {
    userVotes[a.divisionId] = a.vote === "pour" ? 1 : -1;
  }

  // Compute alignment per member
  const memberScores: Record<
    number,
    { name: string; displayName: string; position: string; agreed: number; total: number }
  > = {};

  for (const mv of memberVotes) {
    const mid = mv.member_id as number;
    const did = mv.division_id as number;
    const memberVote = mv.vote === "Pour" ? 1 : -1;
    const userVote = userVotes[did];

    if (userVote === undefined) continue;

    if (!memberScores[mid]) {
      const positions = mv.position_history as { position: string; count: number }[];
      memberScores[mid] = {
        name: mv.canonical_name as string,
        displayName: mv.display_name as string,
        position: positions?.[0]?.position ?? "Member",
        agreed: 0,
        total: 0,
      };
    }

    memberScores[mid].total++;
    if (memberVote === userVote) {
      memberScores[mid].agreed++;
    }
  }

  // Rank by alignment
  const results = Object.values(memberScores)
    .filter((m) => m.total >= 3) // Need at least 3 shared votes
    .map((m) => ({
      name: m.name,
      displayName: m.displayName,
      position: m.position,
      agreementPct: m.total > 0 ? m.agreed / m.total : 0,
      agreed: m.agreed,
      total: m.total,
    }))
    .sort((a, b) => b.agreementPct - a.agreementPct);

  return NextResponse.json({ results });
}
