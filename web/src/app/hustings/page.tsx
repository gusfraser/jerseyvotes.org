import type { Metadata } from "next";
import Link from "next/link";
import { sql, TOPICS } from "@/lib/db";
import { HustingsFilter } from "./filter";

// Render on every request so the "Coverage so far" panel reflects the live
// DB as new hustings are ingested. Without this the page is statically
// rendered at build time and its counts freeze (e.g. showing 31 sessions
// while the homepage — which is force-dynamic — already shows 36+).
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Hustings — Jersey 2026 election",
  description:
    "Transcripts of vote.je hustings (candidate panel events) for the 2026 Jersey election. Browse by event or by policy topic. Display-only — never used to score the matcher quiz.",
};

type EventRow = {
  event_id: number;
  slug: string;
  title: string;
  role: string | null;
  constituency: string | null;
  event_date: string | null;
  youtube_url: string | null;
  duration_seconds: number | null;
  transcript_method: "hand_cleaned" | "auto_pipeline" | "auto_pipeline_reviewed";
  candidate_count: number;
  question_count: number;
};

type TopicRow = {
  topic: string;
  segment_count: number;
  candidate_count: number;
};

type StatsRow = {
  events: number;
  constituencies: number;
  roles: number;
  candidates_speaking: number;
  candidate_segments: number;
  audience_questions: number;
  topic_tags: number;
  topics_covered: number;
  total_duration_seconds: number | null;
  events_with_duration: number;
};

export default async function HustingsIndexPage() {
  const events = (await sql`
    SELECT e.event_id, e.slug, e.title, e.role, e.constituency, e.event_date,
           e.youtube_url, e.duration_seconds, e.transcript_method,
           COUNT(DISTINCT s.candidate_id) FILTER (WHERE s.candidate_id IS NOT NULL) AS candidate_count,
           COUNT(DISTINCT s.question_index) FILTER (WHERE s.question_index IS NOT NULL) AS question_count
    FROM hustings_events e
    LEFT JOIN hustings_segments s ON s.event_id = e.event_id
    WHERE e.election_year = 2026
    GROUP BY e.event_id
    ORDER BY e.role, e.constituency, e.event_date
  `) as unknown as EventRow[];

  const topics = (await sql`
    SELECT t.topic,
           COUNT(t.segment_id) AS segment_count,
           COUNT(DISTINCT s.candidate_id) AS candidate_count
    FROM hustings_segment_topics t
    JOIN hustings_segments s USING (segment_id)
    GROUP BY t.topic
    ORDER BY segment_count DESC
  `) as unknown as TopicRow[];

  const statsRows = (await sql`
    SELECT
      (SELECT COUNT(*)::int FROM hustings_events WHERE election_year = 2026) AS events,
      (SELECT COUNT(DISTINCT constituency)::int FROM hustings_events WHERE election_year = 2026) AS constituencies,
      (SELECT COUNT(DISTINCT role)::int FROM hustings_events WHERE election_year = 2026) AS roles,
      (SELECT COUNT(DISTINCT candidate_id)::int FROM hustings_segments WHERE candidate_id IS NOT NULL) AS candidates_speaking,
      (SELECT COUNT(*)::int FROM hustings_segments WHERE candidate_id IS NOT NULL) AS candidate_segments,
      (SELECT COUNT(*)::int FROM hustings_segments WHERE segment_type = 'audience_question') AS audience_questions,
      (SELECT COUNT(*)::int FROM hustings_segment_topics) AS topic_tags,
      (SELECT COUNT(DISTINCT topic)::int FROM hustings_segment_topics) AS topics_covered,
      (SELECT COALESCE(SUM(duration_seconds), 0)::int FROM hustings_events WHERE election_year = 2026 AND duration_seconds IS NOT NULL) AS total_duration_seconds,
      (SELECT COUNT(*)::int FROM hustings_events WHERE election_year = 2026 AND duration_seconds IS NOT NULL) AS events_with_duration
  `) as unknown as StatsRow[];
  const stats = statsRows[0];

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <header className="mb-10">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100 mb-3">
          Hustings
        </h1>
        <p className="text-gray-600 dark:text-gray-400 max-w-3xl leading-relaxed">
          Transcripts of vote.je hustings (candidate Q&A panels) for the 2026
          Jersey election. Each segment is tagged against the same 16-topic
          taxonomy used elsewhere on this site, so you can compare what
          candidates said when forced to answer questions chosen by the
          audience rather than by themselves.{" "}
          <strong>
            Hustings content is display-only — it&rsquo;s never used to score
            the{" "}
            <Link href="/candidates/quiz" className="underline hover:text-red-700">
              matcher quiz
            </Link>
            .
          </strong>{" "}
          See{" "}
          <Link
            href="/candidates/methodology"
            className="underline hover:text-red-700"
          >
            methodology
          </Link>{" "}
          for the trust boundary and dispute process.
        </p>
        <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm">
          <Link
            href="/candidates/methodology#hustings-transcription"
            className="inline-flex items-center gap-1.5 text-red-700 dark:text-red-400 hover:text-red-900 dark:hover:text-red-300 font-medium"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"
              />
            </svg>
            How these transcripts are produced
          </Link>
          <Link
            href="/candidates/methodology#hustings-quiz-exclusion"
            className="inline-flex items-center gap-1.5 text-gray-600 dark:text-gray-400 hover:text-red-700 dark:hover:text-red-400"
          >
            Why hustings don&rsquo;t score the quiz
          </Link>
        </div>
      </header>

      {events.length > 0 && (
        <section className="mb-10">
          <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 mb-3 uppercase tracking-wide">
            Coverage so far
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            <Stat
              value={String(stats.events)}
              label={`hustings ${stats.events === 1 ? "session" : "sessions"} transcribed`}
            />
            {stats.total_duration_seconds !== null && stats.total_duration_seconds > 0 && (
              <Stat
                value={formatHours(stats.total_duration_seconds)}
                label={
                  stats.events_with_duration < stats.events
                    ? `hours of audio (across ${stats.events_with_duration} of ${stats.events})`
                    : "hours of audio captured"
                }
              />
            )}
            <Stat
              value={String(stats.candidates_speaking)}
              label="candidates with verbatim speech"
            />
            <Stat
              value={String(stats.audience_questions)}
              label="audience questions captured"
            />
            <Stat
              value={String(stats.candidate_segments)}
              label="candidate-attributed speech segments"
            />
            <Stat
              value={String(stats.topic_tags)}
              label={`topic tags applied across ${stats.topics_covered} topics`}
            />
            <Stat
              value={String(stats.constituencies)}
              label={`${stats.constituencies === 1 ? "constituency" : "constituencies"} covered`}
            />
            <Stat
              value={String(stats.roles)}
              label={`role ${stats.roles === 1 ? "type" : "types"} (Connétable / Deputy / Senator)`}
            />
          </div>
        </section>
      )}

      {events.length === 0 ? (
        <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-lg p-10 text-center text-gray-500 dark:text-gray-400">
          No hustings transcripts ingested yet.
        </div>
      ) : (
        <HustingsFilter events={events} />
      )}

      {topics.length > 0 && (
        <section className="mt-12 pt-8 border-t border-gray-200 dark:border-zinc-800">
          <h2 className="text-lg font-semibold text-gray-700 dark:text-gray-300 mb-3 uppercase tracking-wide">
            Browse by topic
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
            See every hustings excerpt tagged with a given topic, grouped by
            constituency.
          </p>
          <div className="flex flex-wrap gap-2">
            {(TOPICS as readonly string[]).map((t) => {
              const stat = topics.find((tr) => tr.topic === t);
              if (!stat) {
                return (
                  <span
                    key={t}
                    className="text-xs text-gray-400 dark:text-gray-600 bg-gray-50 dark:bg-zinc-950 border border-gray-100 dark:border-zinc-800 px-3 py-1.5 rounded-full"
                  >
                    {t}
                    <span className="ml-1.5 opacity-60">0</span>
                  </span>
                );
              }
              return (
                <Link
                  key={t}
                  href={`/hustings/topics/${encodeURIComponent(t)}`}
                  className="text-xs text-gray-700 dark:text-gray-200 bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 px-3 py-1.5 rounded-full hover:border-red-300 hover:text-red-700 transition-colors"
                >
                  {t}
                  <span className="ml-1.5 tabular-nums text-gray-500 dark:text-gray-400">
                    {stat.segment_count}
                  </span>
                </Link>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="bg-gray-50 dark:bg-zinc-950 border border-gray-200 dark:border-zinc-800 rounded-lg p-4">
      <p className="text-2xl sm:text-3xl font-bold text-red-700 tabular-nums">
        {value}
      </p>
      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 leading-snug">
        {label}
      </p>
    </div>
  );
}

function formatHours(totalSeconds: number): string {
  const hours = totalSeconds / 3600;
  if (hours < 1) {
    return `${Math.round(totalSeconds / 60)}m`;
  }
  // Show one decimal when under 10 hours, else round.
  if (hours < 10) {
    return `${hours.toFixed(1)}h`;
  }
  return `${Math.round(hours)}h`;
}
