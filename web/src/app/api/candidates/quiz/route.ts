import { NextResponse } from "next/server";
import { sql, TOPICS, expandConstituency } from "@/lib/db";

// Priority weight for a topic given its rank (0-indexed). The 5 ranked topics
// get weights 5, 4, 3, 2, 1; unranked topics get weight 0. Published in the
// methodology page — keep these constants in sync with that page.
const RANK_WEIGHTS = [5, 4, 3, 2, 1];

// Match = TOPIC_BLEND * T + STANCE_BLEND * S
const TOPIC_BLEND = 0.4;
const STANCE_BLEND = 0.6;

// Threshold below which we mark the result as "low confidence" in the UI.
const LOW_COVERAGE_THRESHOLD = 0.4;

type UserAnswer = "agree" | "disagree" | "neutral" | "skip";

type ScoreInput = {
  priorities: string[];                // ordered list of topics, top 5
  stances: Record<string, UserAnswer>; // question_id -> answer
  constituency?: string | null;
};

type TopicRow = {
  candidate_id: number;
  topic: string;
  salience: number;
};

type StanceRow = {
  candidate_id: number;
  question_id: string;
  stance: "agree" | "disagree" | "neutral" | "not_addressed";
  corrected_stance: "agree" | "disagree" | "neutral" | "not_addressed" | null;
  topic: string;
};

type CandidateRow = {
  candidate_id: number;
  vote_je_slug: string;
  full_name: string;
  role: string | null;
  constituency: string | null;
  party: string | null;
  photo_url: string | null;
  incumbent_member_id: number | null;
  manifesto_word_count: number | null;
  scrape_status: string;
};

export async function GET() {
  // Returns canonical questions grouped by topic, plus the topic list, so the
  // quiz client can render priority step and stance step in one fetch.
  const questions = await sql`
    SELECT question_id, topic, statement, explainer, sort_order
    FROM canonical_questions
    WHERE election_year = 2026
    ORDER BY topic, sort_order
  `;
  const candidateCount = (await sql`
    SELECT COUNT(*)::int AS n FROM candidates
    WHERE election_year = 2026 AND classified_at IS NOT NULL
  `)[0] as { n: number };

  return NextResponse.json({
    topics: TOPICS,
    questions,
    candidateCount: candidateCount.n,
    rankWeights: RANK_WEIGHTS,
    blend: { topic: TOPIC_BLEND, stance: STANCE_BLEND },
  });
}

function rankWeight(topic: string, priorities: string[]): number {
  const idx = priorities.indexOf(topic);
  return idx >= 0 && idx < RANK_WEIGHTS.length ? RANK_WEIGHTS[idx] : 0;
}

export async function POST(request: Request) {
  let body: ScoreInput;
  try {
    body = (await request.json()) as ScoreInput;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const priorities = (body.priorities ?? [])
    .filter((t) => (TOPICS as readonly string[]).includes(t))
    .slice(0, RANK_WEIGHTS.length);
  if (priorities.length === 0) {
    return NextResponse.json(
      { error: "Provide at least one priority topic" },
      { status: 400 },
    );
  }
  const stances = body.stances ?? {};
  const constituency = body.constituency?.trim() || null;
  // Resolve a parish to all relevant constituencies + an "include senators"
  // flag. Senators are island-wide so every voter can vote for them.
  const expansion = expandConstituency(constituency);

  const [candidatesRawAny, topicsRawAny, stancesRawAny, questionRowsAny] = await Promise.all([
    sql`
      SELECT candidate_id, vote_je_slug, full_name, role, constituency, party,
             photo_url, incumbent_member_id, manifesto_word_count, scrape_status
      FROM candidates
      WHERE election_year = 2026
        AND classified_at IS NOT NULL
    `,
    sql`
      SELECT candidate_id, topic, salience
      FROM candidate_topics
    `,
    sql`
      SELECT cs.candidate_id, cs.question_id, cs.stance, cs.corrected_stance,
             cq.topic
      FROM candidate_stances cs
      JOIN canonical_questions cq ON cq.question_id = cs.question_id
      WHERE cq.election_year = 2026
    `,
    sql`
      SELECT question_id, topic FROM canonical_questions WHERE election_year = 2026
    `,
  ]);
  const candidatesRaw = candidatesRawAny as unknown as CandidateRow[];
  const topicsRaw = topicsRawAny as unknown as TopicRow[];
  const stancesRaw = stancesRawAny as unknown as StanceRow[];
  const questionRows = questionRowsAny as unknown as { question_id: string; topic: string }[];

  // Index by candidate
  const topicsByCand = new Map<number, Map<string, number>>();
  for (const t of topicsRaw) {
    if (!topicsByCand.has(t.candidate_id)) {
      topicsByCand.set(t.candidate_id, new Map());
    }
    topicsByCand.get(t.candidate_id)!.set(t.topic, Number(t.salience));
  }

  const stancesByCand = new Map<
    number,
    Map<string, { stance: string; topic: string }>
  >();
  for (const s of stancesRaw) {
    if (!stancesByCand.has(s.candidate_id)) {
      stancesByCand.set(s.candidate_id, new Map());
    }
    stancesByCand.get(s.candidate_id)!.set(s.question_id, {
      stance: s.corrected_stance ?? s.stance,
      topic: s.topic,
    });
  }

  // Pre-compute denominators that depend only on user input.
  const priorityWeightSum = priorities.reduce(
    (sum, t) => sum + rankWeight(t, priorities),
    0,
  );

  // Questions on the user's priority topics — used for coverage denominator.
  const priorityQuestionIds = new Set(
    questionRows
      .filter((q) => priorities.includes(q.topic))
      .map((q) => q.question_id),
  );

  // The user's answered (non-skip) questions, with direction.
  const userAnswers: Record<string, "agree" | "disagree" | "neutral"> = {};
  for (const [qid, ans] of Object.entries(stances)) {
    if (ans === "agree" || ans === "disagree" || ans === "neutral") {
      userAnswers[qid] = ans;
    }
  }

  const results = candidatesRaw
    .filter((c) => {
      if (!expansion.constituencies) return true; // no filter — show all
      if (expansion.includeSenators && c.role === "Senator") return true;
      return c.constituency !== null && expansion.constituencies.includes(c.constituency);
    })
    .map((c) => {
      const candTopics = topicsByCand.get(c.candidate_id) ?? new Map<string, number>();
      const candStances = stancesByCand.get(c.candidate_id) ?? new Map();

      // T: priority-weighted topic salience overlap
      let tNum = 0;
      for (const topic of priorities) {
        const w = rankWeight(topic, priorities);
        const sal = candTopics.get(topic) ?? 0;
        tNum += w * sal;
      }
      const T = priorityWeightSum > 0 ? tNum / priorityWeightSum : 0;

      // S: stance alignment, weighted by topic priority
      let sNum = 0;
      let sDen = 0;
      let matchedQuestions = 0;
      let totalUserQuestions = 0;
      for (const [qid, userAns] of Object.entries(userAnswers)) {
        const candidateStance = candStances.get(qid);
        if (!candidateStance) continue;
        totalUserQuestions++;
        // Only count where BOTH user and candidate took a definite (non-neutral, non-not_addressed) position
        // OR both said neutral — that counts as agreement.
        const candDirectional =
          candidateStance.stance === "agree" || candidateStance.stance === "disagree";
        const candNeutral = candidateStance.stance === "neutral";
        const userDirectional = userAns === "agree" || userAns === "disagree";
        const userNeutral = userAns === "neutral";

        let matched: number | null = null;
        if (candDirectional && userDirectional) {
          matched = userAns === candidateStance.stance ? 1 : 0;
        } else if (candNeutral && userNeutral) {
          matched = 1; // both explicitly neutral
        } else if (
          (candNeutral && userDirectional) ||
          (candDirectional && userNeutral)
        ) {
          matched = 0.5; // one neutral, the other has a position — partial credit
        }
        // Otherwise (candidate didn't address it), skip this question entirely

        if (matched !== null) {
          const w = rankWeight(candidateStance.topic, priorities) || 1;
          // Topics not in user's top-5 still contribute, but with the minimum
          // weight (1) so a candidate isn't penalised when they agree on an
          // off-priority issue.
          sNum += w * matched;
          sDen += w;
          if (matched === 1) matchedQuestions++;
        }
      }
      const S = sDen > 0 ? sNum / sDen : 0;

      // C: coverage on user's priority topics
      const candidateAddressedOnPriorities = [...candStances.entries()].filter(
        ([qid, v]) =>
          priorityQuestionIds.has(qid) && v.stance !== "not_addressed",
      ).length;
      const totalPriorityQuestions = priorityQuestionIds.size;
      const C =
        totalPriorityQuestions > 0
          ? candidateAddressedOnPriorities / totalPriorityQuestions
          : 0;

      const match = TOPIC_BLEND * T + STANCE_BLEND * S;

      return {
        candidate_id: c.candidate_id,
        slug: c.vote_je_slug,
        name: c.full_name,
        role: c.role,
        constituency: c.constituency,
        party: c.party,
        photo_url: c.photo_url,
        is_incumbent: c.incumbent_member_id !== null,
        incumbent_member_id: c.incumbent_member_id,
        manifesto_word_count: c.manifesto_word_count,
        scrape_status: c.scrape_status,
        T: round2(T),
        S: round2(S),
        C: round2(C),
        match: round2(match),
        matched_questions: matchedQuestions,
        answered_questions: totalUserQuestions,
        low_coverage: C < LOW_COVERAGE_THRESHOLD,
      };
    });

  // Sort by match desc, then by S desc, then alphabetical (no false precision
  // tiebreaks). We expose Math.round(match*100) so 0.001 differences don't ranks.
  results.sort((a, b) => {
    const ma = Math.round(a.match * 100);
    const mb = Math.round(b.match * 100);
    if (mb !== ma) return mb - ma;
    if (b.S !== a.S) return b.S - a.S;
    return a.name.localeCompare(b.name);
  });

  return NextResponse.json({
    results,
    priorities,
    constituency,
    config: {
      rankWeights: RANK_WEIGHTS,
      blend: { topic: TOPIC_BLEND, stance: STANCE_BLEND },
      lowCoverageThreshold: LOW_COVERAGE_THRESHOLD,
    },
  });
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
