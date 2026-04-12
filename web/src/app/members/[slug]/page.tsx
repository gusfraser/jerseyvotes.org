import Link from "next/link";
import { notFound } from "next/navigation";
import { sql } from "@/lib/db";
import { slugify } from "@/lib/slugify";

export default async function MemberPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;

  // Find member by matching slugified name
  const members = await sql`SELECT * FROM members ORDER BY canonical_name`;
  const member = members.find(
    (m: Record<string, unknown>) =>
      slugify(m.canonical_name as string) === slug
  );
  if (!member) notFound();

  const memberId = member.member_id as number;

  const [voteStats, recentVotes, topicBreakdown] = await Promise.all([
    sql`SELECT
          COUNT(*) as total_divisions,
          COUNT(CASE WHEN vote_category = 'active_vote' THEN 1 END) as active_votes,
          COUNT(CASE WHEN vote = 'Pour' THEN 1 END) as pour,
          COUNT(CASE WHEN vote = 'Contre' THEN 1 END) as contre,
          COUNT(CASE WHEN vote = 'Abstained' THEN 1 END) as abstained,
          COUNT(CASE WHEN vote_category = 'unexcused_absence' THEN 1 END) as unexcused,
          COUNT(CASE WHEN vote_category = 'excused_absence' THEN 1 END) as excused
        FROM votes WHERE member_id = ${memberId}`,
    sql`SELECT v.vote, vd.proposition_title, vd.date, vd.division_id,
             vd.reference, vd.pour_count, vd.contre_count, vd.division_stage,
             p.topic_primary
           FROM votes v
           JOIN vote_divisions vd ON v.division_id = vd.division_id
           JOIN propositions p ON vd.proposition_id = p.proposition_id
           WHERE v.member_id = ${memberId}
             AND v.vote IN ('Pour', 'Contre', 'Abstained')
             AND vd.division_stage IN ('principles', 'third_reading')
           ORDER BY vd.date DESC LIMIT 20`,
    sql`SELECT p.topic_primary, COUNT(*) as count,
             COUNT(CASE WHEN v.vote = 'Pour' THEN 1 END) as pour,
             COUNT(CASE WHEN v.vote = 'Contre' THEN 1 END) as contre
           FROM votes v
           JOIN vote_divisions vd ON v.division_id = vd.division_id
           JOIN propositions p ON vd.proposition_id = p.proposition_id
           WHERE v.member_id = ${memberId}
             AND v.vote IN ('Pour', 'Contre')
             AND p.topic_primary IS NOT NULL
           GROUP BY p.topic_primary
           ORDER BY count DESC`,
  ]);

  const stats = voteStats[0];
  const positions = member.position_history as {
    position: string;
    count: number;
  }[];
  const mainPosition = positions?.[0]?.position ?? "Member";

  const participation =
    (stats.total_divisions as number) > 0
      ? ((stats.active_votes as number) / (stats.total_divisions as number)) *
        100
      : 0;

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <Link
        href="/members"
        className="text-sm text-gray-500 hover:text-red-700 mb-4 inline-block"
      >
        &larr; All Members
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold">
            {member.display_name as string}
          </h1>
          <p className="text-lg text-gray-500 mt-1">{mainPosition}</p>
          <p className="text-sm text-gray-400 mt-1">
            {new Date(member.first_vote_date as string).toLocaleDateString(
              "en-GB",
              { month: "short", year: "numeric" }
            )}{" "}
            &ndash;{" "}
            {new Date(member.last_vote_date as string).toLocaleDateString(
              "en-GB",
              { month: "short", year: "numeric" }
            )}
          </p>
        </div>
        {member.is_currently_active && (
          <span className="bg-green-100 text-green-700 px-3 py-1 rounded-full text-sm font-medium">
            Currently Active
          </span>
        )}
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
        <StatBox
          label="Participation"
          value={`${participation.toFixed(1)}%`}
        />
        <StatBox
          label="Pour"
          value={Number(stats.pour).toLocaleString()}
          color="text-green-600"
        />
        <StatBox
          label="Contre"
          value={Number(stats.contre).toLocaleString()}
          color="text-red-600"
        />
        <StatBox
          label="Abstained"
          value={String(stats.abstained)}
          color="text-yellow-600"
        />
        <StatBox
          label="Absences"
          value={String(stats.unexcused)}
          color="text-gray-500"
        />
      </div>

      <div className="grid lg:grid-cols-3 gap-8">
        {/* Recent votes */}
        <div className="lg:col-span-2">
          <h2 className="text-xl font-semibold mb-4">
            Recent Key Votes
          </h2>
          <div className="space-y-2">
            {recentVotes.map((v: Record<string, unknown>) => (
              <Link
                key={v.division_id as number}
                href={`/votes/${v.division_id}`}
                className="flex items-center gap-3 bg-white rounded-lg border border-gray-200 p-3 hover:border-red-300 transition-colors"
              >
                <span
                  className={`w-16 text-center text-xs font-semibold px-2 py-1 rounded ${
                    v.vote === "Pour"
                      ? "bg-green-100 text-green-700"
                      : v.vote === "Contre"
                      ? "bg-red-100 text-red-700"
                      : "bg-yellow-100 text-yellow-700"
                  }`}
                >
                  {v.vote as string}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">
                    {v.proposition_title as string}
                  </p>
                  <p className="text-xs text-gray-400">
                    {v.reference as string} &middot;{" "}
                    {new Date(v.date as string).toLocaleDateString("en-GB", {
                      day: "numeric",
                      month: "short",
                      year: "numeric",
                    })}
                  </p>
                </div>
                <span className="text-xs text-gray-400 whitespace-nowrap">
                  {v.pour_count as number}-{v.contre_count as number}
                </span>
              </Link>
            ))}
          </div>
        </div>

        {/* Topic breakdown */}
        <div>
          <h2 className="text-xl font-semibold mb-4">
            Voting by Topic
          </h2>
          <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
            {topicBreakdown.map((t: Record<string, unknown>) => {
              const pour = Number(t.pour);
              const contre = Number(t.contre);
              const total = pour + contre;
              const pourPct = total > 0 ? (pour / total) * 100 : 50;
              return (
                <div key={t.topic_primary as string}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-gray-700 truncate">
                      {t.topic_primary as string}
                    </span>
                    <span className="text-gray-400 text-xs">
                      {t.count as number} votes
                    </span>
                  </div>
                  <div className="h-2 bg-red-400 rounded-full overflow-hidden">
                    <div
                      className="bg-green-400 h-full rounded-full"
                      style={{ width: `${pourPct}%` }}
                    />
                  </div>
                  <div className="flex justify-between text-xs text-gray-400 mt-0.5">
                    <span>{pour} Pour</span>
                    <span>{contre} Contre</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function StatBox({
  label,
  value,
  color = "text-gray-900",
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
      <p className="text-xs text-gray-500 mt-1">{label}</p>
    </div>
  );
}
