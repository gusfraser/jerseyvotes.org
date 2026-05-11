import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { sql } from "@/lib/db";
import { CorrectionForm } from "./correction-form";

// Token-gated preview. Crawlers must not index this.
export const metadata: Metadata = {
  title: "Review your candidate profile",
  robots: { index: false, follow: false },
};

type CandidateWithExtractions = {
  candidate_id: number;
  vote_je_slug: string;
  full_name: string;
  role: string | null;
  constituency: string | null;
  party: string | null;
  manifesto_text: string | null;
  manifesto_word_count: number | null;
  correction_state: string;
  scraped_at: string;
  classified_at: string | null;
};

type TopicRow = {
  topic: string;
  salience: number;
  summary: string | null;
  source_quote: string | null;
};

type StanceRow = {
  question_id: string;
  topic: string;
  statement: string;
  stance: "agree" | "disagree" | "neutral" | "not_addressed";
  corrected_stance: "agree" | "disagree" | "neutral" | "not_addressed" | null;
  source_quote: string | null;
};

export default async function CorrectionPreview({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const rows = (await sql`
    SELECT candidate_id, vote_je_slug, full_name, role, constituency, party,
           manifesto_text, manifesto_word_count, correction_state,
           scraped_at, classified_at
    FROM candidates
    WHERE correction_token = ${token}
    LIMIT 1
  `) as unknown as CandidateWithExtractions[];

  const candidate = rows[0];
  if (!candidate) notFound();

  const [topicsAny, stancesAny] = await Promise.all([
    sql`
      SELECT topic, salience, summary, source_quote
      FROM candidate_topics
      WHERE candidate_id = ${candidate.candidate_id}
      ORDER BY salience DESC
    `,
    sql`
      SELECT cs.question_id, cs.stance, cs.corrected_stance, cs.source_quote,
             cq.topic, cq.statement
      FROM candidate_stances cs
      JOIN canonical_questions cq ON cq.question_id = cs.question_id
      WHERE cs.candidate_id = ${candidate.candidate_id}
      ORDER BY cq.topic, cq.sort_order
    `,
  ]);
  const topics = topicsAny as unknown as TopicRow[];
  const stances = stancesAny as unknown as StanceRow[];

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <div className="bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-800 rounded-lg p-4 mb-6">
        <p className="font-semibold text-amber-900 dark:text-amber-200 mb-1">
          Private preview — not yet public
        </p>
        <p className="text-sm text-amber-800 dark:text-amber-300">
          This is a private review link for{" "}
          <strong>{candidate.full_name}</strong>. Please check that the topics
          and policy positions below correctly reflect your manifesto. If
          anything is wrong, use the form at the bottom of this page to flag it.
        </p>
      </div>

      <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100 mb-1">
        {candidate.full_name}
      </h1>
      <p className="text-gray-500 dark:text-gray-400 mb-6">
        {[candidate.role, candidate.constituency, candidate.party]
          .filter(Boolean)
          .join(" — ")}
      </p>

      <section className="mb-8">
        <h2 className="text-xl font-bold mb-3 text-gray-900 dark:text-gray-100">
          Topics we identified
        </h2>
        {topics.length === 0 ? (
          <p className="text-gray-500 dark:text-gray-400 text-sm italic">
            No topics extracted yet.
          </p>
        ) : (
          <div className="space-y-3">
            {topics.map((t) => (
              <div
                key={t.topic}
                className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-lg p-4"
              >
                <div className="flex items-center justify-between mb-1">
                  <p className="font-medium text-gray-900 dark:text-gray-100">{t.topic}</p>
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {Math.round(t.salience * 100)}% of manifesto
                  </span>
                </div>
                {t.summary && (
                  <p className="text-sm text-gray-700 dark:text-gray-300 mb-1">{t.summary}</p>
                )}
                {t.source_quote && (
                  <blockquote className="pl-3 border-l-2 border-gray-300 text-xs italic text-gray-500 dark:text-gray-400">
                    &ldquo;{t.source_quote}&rdquo;
                  </blockquote>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="mb-8">
        <h2 className="text-xl font-bold mb-3 text-gray-900 dark:text-gray-100">
          Policy positions
        </h2>
        <div className="space-y-3">
          {stances.map((s) => {
            const current = s.corrected_stance ?? s.stance;
            return (
              <div
                key={s.question_id}
                className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-lg p-4"
              >
                <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
                  {s.topic}
                </p>
                <p className="text-sm text-gray-900 dark:text-gray-100 mb-2">
                  {s.statement}
                </p>
                <p className="text-sm">
                  Our reading:{" "}
                  <span className="font-medium">
                    {labelFor(current)}
                  </span>
                  {s.corrected_stance && (
                    <span className="ml-2 text-xs text-green-700 dark:text-green-300">
                      (corrected from {labelFor(s.stance)})
                    </span>
                  )}
                </p>
                {s.source_quote && current !== "not_addressed" && (
                  <blockquote className="mt-2 pl-3 border-l-2 border-gray-300 text-xs italic text-gray-500 dark:text-gray-400">
                    &ldquo;{s.source_quote}&rdquo;
                  </blockquote>
                )}
              </div>
            );
          })}
        </div>
      </section>

      <section className="mb-8">
        <h2 className="text-xl font-bold mb-3 text-gray-900 dark:text-gray-100">
          Flag a correction
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-3">
          If we&rsquo;ve got something wrong, tell us specifically which topic
          or statement and what should change. We process valid corrections
          within 24 hours.
        </p>
        <CorrectionForm token={token} />
      </section>

      <p className="text-xs text-gray-500 dark:text-gray-400">
        See the public methodology at{" "}
        <Link href="/candidates/methodology" className="underline hover:text-red-700">
          /candidates/methodology
        </Link>
        . This page is unlisted and not indexed by search engines.
      </p>
    </div>
  );
}

function labelFor(s: string): string {
  switch (s) {
    case "agree":
      return "Agree";
    case "disagree":
      return "Disagree";
    case "neutral":
      return "Neutral";
    case "not_addressed":
      return "Not addressed in manifesto";
    default:
      return s;
  }
}
