import Link from "next/link";
import { sql } from "@/lib/db";

export default async function Home() {
  const [statsResult, recentVotes, topicCounts] = await Promise.all([
    sql`SELECT
      (SELECT COUNT(*) FROM members WHERE is_currently_active) as active_members,
      (SELECT COUNT(*) FROM propositions) as total_propositions,
      (SELECT COUNT(*) FROM vote_divisions) as total_divisions,
      (SELECT MIN(date)::date FROM vote_divisions) as earliest_date,
      (SELECT MAX(date)::date FROM vote_divisions) as latest_date`,
    sql`SELECT vd.division_id, vd.proposition_title, vd.date, vd.reference,
           vd.pour_count, vd.contre_count, vd.division_stage,
           p.topic_primary, p.source_url
         FROM vote_divisions vd
         JOIN propositions p ON vd.proposition_id = p.proposition_id
         WHERE vd.division_stage IN ('principles', 'third_reading')
         ORDER BY vd.date DESC LIMIT 8`,
    sql`SELECT topic_primary, COUNT(*) as count
         FROM propositions
         WHERE topic_primary IS NOT NULL
         GROUP BY topic_primary
         ORDER BY count DESC`,
  ]);

  const stats = statsResult[0];

  return (
    <div>
      {/* Hero */}
      <section className="bg-gradient-to-br from-red-800 to-red-950 text-white py-16">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
          <h1 className="text-4xl font-bold mb-4">
            How does your Assembly vote?
          </h1>
          <p className="text-xl text-red-100 max-w-2xl mb-8">
            Explore 22 years of Jersey States Assembly voting data. See which
            politicians vote together, who votes independently, and find
            representatives aligned with your views.
          </p>
          <div className="flex gap-4">
            <Link
              href="/quiz"
              className="bg-white text-red-800 px-6 py-3 rounded-lg font-semibold hover:bg-red-50 transition-colors"
            >
              Take the Voter Quiz
            </Link>
            <Link
              href="/members"
              className="border border-white/30 text-white px-6 py-3 rounded-lg font-semibold hover:bg-white/10 transition-colors"
            >
              Explore Members
            </Link>
          </div>
        </div>
      </section>

      {/* Stats bar */}
      <section className="bg-white border-b border-gray-200">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
            <StatCard
              label="Active Members"
              value={String(stats.active_members)}
            />
            <StatCard
              label="Propositions"
              value={Number(stats.total_propositions).toLocaleString()}
            />
            <StatCard
              label="Recorded Votes"
              value={Number(stats.total_divisions).toLocaleString()}
            />
            <StatCard label="Years of Data" value="22" />
          </div>
        </div>
      </section>

      {/* Main content */}
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="grid lg:grid-cols-3 gap-8">
          {/* Recent key votes */}
          <div className="lg:col-span-2">
            <h2 className="text-2xl font-bold mb-6">Recent Key Votes</h2>
            <div className="space-y-3">
              {recentVotes.map((vote: Record<string, unknown>) => (
                <Link
                  key={vote.division_id as number}
                  href={`/votes/${vote.division_id}`}
                  className="block bg-white rounded-lg border border-gray-200 p-4 hover:border-red-300 hover:shadow-sm transition-all"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-gray-900 truncate">
                        {vote.proposition_title as string}
                      </p>
                      <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
                        <span>{vote.reference as string}</span>
                        <span>
                          {new Date(
                            vote.date as string
                          ).toLocaleDateString("en-GB", {
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                          })}
                        </span>
                        {Boolean(vote.topic_primary) && (
                          <span className="bg-gray-100 px-2 py-0.5 rounded text-xs">
                            {vote.topic_primary as string}
                          </span>
                        )}
                      </div>
                    </div>
                    <VoteBadge
                      pour={vote.pour_count as number}
                      contre={vote.contre_count as number}
                    />
                  </div>
                </Link>
              ))}
            </div>
            <Link
              href="/votes"
              className="inline-block mt-4 text-red-700 hover:underline font-medium"
            >
              View all votes &rarr;
            </Link>
          </div>

          {/* Topics sidebar */}
          <div>
            <h2 className="text-2xl font-bold mb-6">Topics</h2>
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <div className="space-y-2">
                {topicCounts.map((topic: Record<string, unknown>) => (
                  <div
                    key={topic.topic_primary as string}
                    className="flex items-center justify-between text-sm"
                  >
                    <span className="text-gray-700">
                      {topic.topic_primary as string}
                    </span>
                    <span className="text-gray-400 tabular-nums">
                      {topic.count as number}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Quick links */}
            <h2 className="text-2xl font-bold mt-8 mb-6">Explore</h2>
            <div className="space-y-3">
              {[
                {
                  href: "/alignment",
                  title: "Alignment Matrix",
                  desc: "See which members vote together",
                },
                {
                  href: "/blocs",
                  title: "Voting Blocs",
                  desc: "Discover informal coalitions",
                },
                {
                  href: "/members",
                  title: "Member Profiles",
                  desc: "Individual voting records",
                },
              ].map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="block bg-white rounded-lg border border-gray-200 p-4 hover:border-red-300 transition-colors"
                >
                  <p className="font-medium text-gray-900">{link.title}</p>
                  <p className="text-sm text-gray-500">{link.desc}</p>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-center">
      <p className="text-3xl font-bold text-red-700">{value}</p>
      <p className="text-sm text-gray-500 mt-1">{label}</p>
    </div>
  );
}

function VoteBadge({ pour, contre }: { pour: number; contre: number }) {
  const passed = pour > contre;
  return (
    <div
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium whitespace-nowrap ${
        passed ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
      }`}
    >
      <span>{pour}</span>
      <span className="text-gray-400">-</span>
      <span>{contre}</span>
    </div>
  );
}
