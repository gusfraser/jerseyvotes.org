import Link from "next/link";
import { sql, daysUntilElection } from "@/lib/db";
import { TrackedLink } from "@/lib/track-click";

const JERSEY_CONSTITUENCIES = [
  // 12 parishes (Connétable)
  "St Helier",
  "St Saviour",
  "St Brelade",
  "St Clement",
  "St Lawrence",
  "Trinity",
  "Grouville",
  "St Peter",
  "St Ouen",
  "St John",
  "St Martin",
  "St Mary",
];

export default async function Home() {
  const days = daysUntilElection();

  const [statsResult, candidateStats, recentVotes] = await Promise.all([
    sql`SELECT
      (SELECT COUNT(*) FROM members WHERE is_currently_active) as active_members,
      (SELECT COUNT(*) FROM propositions) as total_propositions,
      (SELECT COUNT(*) FROM vote_divisions) as total_divisions`,
    sql`SELECT
      (SELECT COUNT(*) FROM candidates WHERE election_year = 2026) as total_candidates,
      (SELECT COUNT(*) FROM candidates WHERE election_year = 2026 AND incumbent_member_id IS NOT NULL) as incumbents,
      (SELECT COUNT(DISTINCT constituency) FROM candidates WHERE election_year = 2026 AND constituency IS NOT NULL) as constituency_count,
      (SELECT COUNT(*) FROM candidates WHERE election_year = 2026 AND classified_at IS NOT NULL) as classified`,
    sql`SELECT vd.division_id, vd.proposition_title, vd.date, vd.reference,
           vd.pour_count, vd.contre_count, vd.division_stage,
           p.topic_primary, p.source_url
         FROM vote_divisions vd
         JOIN propositions p ON vd.proposition_id = p.proposition_id
         WHERE vd.division_stage IN ('principles', 'third_reading')
         ORDER BY vd.date DESC LIMIT 6`,
  ]);

  const stats = statsResult[0];
  const cstats = candidateStats[0];
  const totalCandidates = Number(cstats?.total_candidates ?? 0);
  const incumbentCount = Number(cstats?.incumbents ?? 0);
  const hasCandidateData = totalCandidates > 0;

  return (
    <div>
      {/* Election countdown hero */}
      <section className="bg-gradient-to-br from-red-800 via-red-900 to-red-950 text-white">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12 sm:py-16">
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex items-center gap-2 bg-white/15 text-red-100 px-3 py-1 rounded-full text-sm font-medium">
              <span className="w-2 h-2 bg-red-300 rounded-full animate-pulse" />
              Jersey general election
            </span>
            <span className="text-red-200 text-sm">
              {new Date("2026-06-07T00:00:00Z").toLocaleDateString("en-GB", {
                weekday: "long",
                day: "numeric",
                month: "long",
                year: "numeric",
              })}
            </span>
          </div>
          <h1 className="text-4xl sm:text-5xl font-bold mb-3 tracking-tight">
            {days > 0 ? (
              <>
                <span className="text-red-200">{days}</span>{" "}
                {days === 1 ? "day" : "days"} until you vote
              </>
            ) : (
              "Polls have opened"
            )}
          </h1>
          <p className="text-xl text-red-100 max-w-2xl mb-8">
            Find the candidates whose priorities match yours. Free, independent,
            and based on every candidate&rsquo;s own published manifesto.
          </p>
          <div className="flex flex-wrap gap-3">
            <TrackedLink
              href="/candidates/quiz"
              event="home_cta_clicked"
              params={{ cta: "find_your_candidate" }}
              className="bg-white text-red-800 px-6 py-3 rounded-lg font-semibold hover:bg-red-50 transition-colors"
            >
              Find your candidate &rarr;
            </TrackedLink>
            <TrackedLink
              href="/candidates"
              event="home_cta_clicked"
              params={{ cta: "browse_candidates" }}
              className="border border-white/30 text-white px-6 py-3 rounded-lg font-semibold hover:bg-white/10 transition-colors"
            >
              {hasCandidateData
                ? `Browse all ${totalCandidates} candidates`
                : "Browse candidates"}
            </TrackedLink>
          </div>
          <p className="mt-4 text-sm text-red-200">
            <TrackedLink
              href="/candidates/methodology"
              event="home_cta_clicked"
              params={{ cta: "read_methodology" }}
              className="underline hover:text-white"
            >
              Read how we score candidates
            </TrackedLink>
          </p>
        </div>
      </section>

      {/* How it works */}
      <section className="bg-white dark:bg-zinc-900 border-b border-gray-200 dark:border-zinc-800">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
          <h2 className="text-2xl font-bold mb-6 text-gray-900 dark:text-gray-100">
            How it works
          </h2>
          <div className="grid md:grid-cols-3 gap-4">
            <HowItWorksCard
              n={1}
              title="Tell us your priorities"
              body="Rank the 16 policy areas by what matters most to you."
            />
            <HowItWorksCard
              n={2}
              title="Answer about 40 policy questions"
              body="Agree, disagree, or skip on Jersey-specific statements."
            />
            <HowItWorksCard
              n={3}
              title="See your ranked matches"
              body="Every score is broken down by topic, with manifesto quotes you can verify."
            />
          </div>
          <div className="mt-6">
            <Link
              href="/candidates/quiz"
              className="inline-block bg-red-700 text-white px-5 py-2.5 rounded-lg font-medium hover:bg-red-800 transition-colors"
            >
              Start the quiz
            </Link>
          </div>
        </div>
      </section>

      {/* Constituency quick-jump */}
      <section className="bg-gray-50 dark:bg-zinc-950 border-b border-gray-200 dark:border-zinc-800">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
          <h2 className="text-2xl font-bold mb-2 text-gray-900 dark:text-gray-100">
            Know your parish? Jump straight in.
          </h2>
          <p className="text-gray-500 dark:text-gray-400 mb-5">
            See the candidates you can actually vote for: 1 Connétable for your
            parish, 2&ndash;4 Deputies for your constituency, and up to 9 Senators
            (island-wide).{" "}
            <a
              href="https://www.vote.je/constituency-finder/"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-red-700"
            >
              Find your constituency by postcode
            </a>
            .
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
            {JERSEY_CONSTITUENCIES.map((c) => (
              <Link
                key={c}
                href={`/candidates?constituency=${encodeURIComponent(c)}`}
                className="block bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 px-3 py-2 rounded-md text-sm text-gray-700 dark:text-gray-200 hover:border-red-300 hover:text-red-700 transition-colors"
              >
                {c}
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* Data confidence strip */}
      {hasCandidateData && (
        <section className="bg-white dark:bg-zinc-900 border-b border-gray-200 dark:border-zinc-800">
          <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 grid grid-cols-2 sm:grid-cols-4 gap-6">
            <StatCard label="Candidates analysed" value={totalCandidates.toString()} />
            <StatCard label="Sitting members standing" value={incumbentCount.toString()} />
            <StatCard label="Parishes covered" value={String(cstats.constituency_count ?? 0)} />
            <StatCard label="Years of voting data" value="22" />
          </div>
        </section>
      )}

      {/* Recent key votes (demoted) */}
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="grid lg:grid-cols-3 gap-8">
          <div className="lg:col-span-2">
            <div className="flex items-baseline justify-between mb-4">
              <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">
                Evaluating an incumbent?
              </h2>
              <Link
                href="/votes"
                className="text-sm text-red-700 hover:underline"
              >
                All votes &rarr;
              </Link>
            </div>
            <p className="text-gray-500 dark:text-gray-400 mb-4 text-sm">
              The Assembly&rsquo;s most recent recorded votes. Useful for
              checking what sitting members have done lately.
            </p>
            <div className="space-y-2">
              {recentVotes.map((vote: Record<string, unknown>) => (
                <Link
                  key={vote.division_id as number}
                  href={`/votes/${vote.division_id}`}
                  className="block bg-white dark:bg-zinc-900 rounded-lg border border-gray-200 dark:border-zinc-800 p-3 hover:border-red-300 transition-colors"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-gray-900 dark:text-gray-100 truncate text-sm">
                        {vote.proposition_title as string}
                      </p>
                      <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                        <span>{vote.reference as string}</span>
                        <span>
                          {new Date(vote.date as string).toLocaleDateString("en-GB", {
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                          })}
                        </span>
                        {Boolean(vote.topic_primary) && (
                          <span className="bg-gray-100 dark:bg-zinc-800 px-2 py-0.5 rounded">
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
          </div>

          <div>
            <h2 className="text-xl font-bold mb-4 text-gray-900 dark:text-gray-100">
              Also explore
            </h2>
            <div className="space-y-3">
              {[
                {
                  href: "/members",
                  title: "Member profiles",
                  desc: "Individual voting records",
                },
                {
                  href: "/alignment",
                  title: "Alignment matrix",
                  desc: "Which members vote together",
                },
                {
                  href: "/blocs",
                  title: "Voting blocs",
                  desc: "Informal coalitions",
                },
                {
                  href: "/quiz",
                  title: "Voting Quiz",
                  desc: "Match yourself to a sitting member by past votes",
                },
              ].map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="block bg-white dark:bg-zinc-900 rounded-lg border border-gray-200 dark:border-zinc-800 p-3 hover:border-red-300 transition-colors"
                >
                  <p className="font-medium text-gray-900 dark:text-gray-100 text-sm">{link.title}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">{link.desc}</p>
                </Link>
              ))}
            </div>

            <div className="mt-6 text-xs text-gray-400 dark:text-gray-500">
              {Number(stats.active_members)} active members · {Number(stats.total_propositions).toLocaleString()} propositions · {Number(stats.total_divisions).toLocaleString()} recorded votes
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function HowItWorksCard({ n, title, body }: { n: number; title: string; body: string }) {
  return (
    <div className="bg-gray-50 dark:bg-zinc-950 border border-gray-200 dark:border-zinc-800 rounded-lg p-5">
      <div className="w-7 h-7 rounded-full bg-red-700 text-white text-sm font-bold flex items-center justify-center mb-3">
        {n}
      </div>
      <p className="font-semibold text-gray-900 dark:text-gray-100 mb-1">{title}</p>
      <p className="text-sm text-gray-500 dark:text-gray-400">{body}</p>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-center">
      <p className="text-3xl font-bold text-red-700">{value}</p>
      <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">{label}</p>
    </div>
  );
}

function VoteBadge({ pour, contre }: { pour: number; contre: number }) {
  const passed = pour > contre;
  return (
    <div
      className={`flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium whitespace-nowrap ${
        passed ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
      }`}
    >
      <span>{pour}</span>
      <span className="text-gray-400">-</span>
      <span>{contre}</span>
    </div>
  );
}
