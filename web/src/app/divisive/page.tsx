import type { Metadata } from "next";
import Link from "next/link";
import { sql } from "@/lib/db";

export const metadata: Metadata = {
  title: "Most Divisive",
  description:
    "Which topics and votes split the Jersey States Assembly most evenly? See the closest votes and most contested policy areas.",
};

export default async function DivisivePage() {
  const [topicRows, closeVotes] = await Promise.all([
    sql`
      SELECT p.topic_primary,
             COUNT(*) as vote_count,
             AVG(LEAST(vd.pour_count, vd.contre_count)::float
                 / NULLIF(vd.pour_count + vd.contre_count, 0)) as avg_closeness
      FROM vote_divisions vd
      JOIN propositions p ON vd.proposition_id = p.proposition_id
      WHERE vd.division_stage IN ('principles', 'third_reading', 'amendment')
        AND p.topic_primary IS NOT NULL
        AND (vd.pour_count + vd.contre_count) >= 10
        AND vd.date >= '2022-07-01'
      GROUP BY p.topic_primary
      HAVING COUNT(*) >= 3
      ORDER BY avg_closeness DESC
    `,
    sql`
      SELECT vd.division_id, vd.proposition_title, vd.date,
             vd.pour_count, vd.contre_count, vd.division_stage,
             p.base_reference, p.topic_primary, p.plain_language_summary,
             LEAST(vd.pour_count, vd.contre_count)::float
               / NULLIF(vd.pour_count + vd.contre_count, 0) as closeness
      FROM vote_divisions vd
      JOIN propositions p ON vd.proposition_id = p.proposition_id
      WHERE vd.division_stage IN ('principles', 'third_reading', 'amendment')
        AND (vd.pour_count + vd.contre_count) >= 20
        AND vd.date >= '2022-07-01'
      ORDER BY closeness DESC
      LIMIT 25
    `,
  ]);

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <h1 className="text-3xl font-bold mb-2">Most Divisive</h1>
      <p className="text-gray-600 mb-10 max-w-3xl">
        What splits the Assembly? These are the topics and votes where members
        disagree most, based on key votes (Principles, Third Reading, and
        Amendments) in the current term (2022&ndash;present).
      </p>

      {/* Topics That Divide */}
      <section className="mb-14">
        <h2 className="text-xl font-bold mb-1">Topics That Divide</h2>
        <p className="text-sm text-gray-500 mb-6">
          Average share of the minority side per topic. Closer to 50% means more
          evenly split.
        </p>
        <div className="space-y-3">
          {topicRows.map((t: Record<string, unknown>) => {
            const closeness = Number(t.avg_closeness);
            const pct = Math.round(closeness * 100);
            // Scale the bar: 0% minority = 0 width, 50% = full width
            const barWidth = (closeness / 0.5) * 100;
            return (
              <div key={t.topic_primary as string}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-gray-900">
                    {t.topic_primary as string}
                  </span>
                  <span className="text-sm text-gray-500 tabular-nums">
                    {pct}% avg. minority &middot; {t.vote_count as number} votes
                  </span>
                </div>
                <div className="h-3 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      pct >= 10
                        ? "bg-red-500"
                        : pct >= 5
                        ? "bg-amber-500"
                        : "bg-gray-300"
                    }`}
                    style={{ width: `${barWidth}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
        <p className="text-xs text-gray-400 mt-4">
          Red = highly contested (close to 50-50 splits). Only topics with 3+ votes shown.
        </p>
      </section>

      {/* Closest Votes */}
      <section>
        <h2 className="text-xl font-bold mb-1">Closest Votes</h2>
        <p className="text-sm text-gray-500 mb-6">
          The 25 most evenly split votes in the current term. These are the
          issues that truly divided the Assembly.
        </p>
        <div className="space-y-3">
          {closeVotes.map((v: Record<string, unknown>) => {
            const pour = v.pour_count as number;
            const contre = v.contre_count as number;
            const total = pour + contre;
            const pourPct = (pour / total) * 100;
            const passed = pour > contre;
            return (
              <Link
                key={v.division_id as number}
                href={`/votes/${v.division_id}`}
                className="block bg-white rounded-lg border border-gray-200 p-4 hover:border-red-300 hover:shadow-sm transition-all"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-gray-900">
                      {v.plain_language_summary
                        ? (v.plain_language_summary as string)
                        : (v.proposition_title as string)}
                    </p>
                    {v.plain_language_summary && (
                      <p className="text-xs text-gray-400 mt-0.5 truncate">
                        {v.proposition_title as string}
                      </p>
                    )}
                    <div className="flex items-center gap-2 mt-2 text-xs text-gray-500">
                      <span>{v.base_reference as string}</span>
                      <span>
                        {new Date(v.date as string).toLocaleDateString(
                          "en-GB",
                          { day: "numeric", month: "short", year: "numeric" }
                        )}
                      </span>
                      {v.topic_primary && (
                        <span className="bg-gray-100 px-2 py-0.5 rounded">
                          {v.topic_primary as string}
                        </span>
                      )}
                      <span className="capitalize">
                        {(v.division_stage as string).replace("_", " ")}
                      </span>
                    </div>
                  </div>
                  <div className="flex flex-col items-end shrink-0">
                    <div
                      className={`text-lg font-bold tabular-nums ${
                        passed ? "text-green-600" : "text-red-600"
                      }`}
                    >
                      {pour}-{contre}
                    </div>
                    <span
                      className={`text-xs font-medium ${
                        passed ? "text-green-600" : "text-red-600"
                      }`}
                    >
                      {passed ? "Adopted" : "Rejected"}
                    </span>
                  </div>
                </div>
                {/* Split bar */}
                <div className="mt-3 flex h-2 rounded-full overflow-hidden">
                  <div
                    className="bg-green-400"
                    style={{ width: `${pourPct}%` }}
                  />
                  <div
                    className="bg-red-400"
                    style={{ width: `${100 - pourPct}%` }}
                  />
                </div>
              </Link>
            );
          })}
        </div>
      </section>
    </div>
  );
}
