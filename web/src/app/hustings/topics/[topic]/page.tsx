import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { sql, TOPICS } from "@/lib/db";
import { TranscriptMethodBadge, type TranscriptMethod } from "../../transcript-method-badge";

type SegmentRow = {
  segment_id: number;
  event_slug: string;
  event_title: string;
  event_role: string | null;
  event_constituency: string | null;
  transcript_method: TranscriptMethod;
  candidate_id: number | null;
  candidate_name: string | null;
  candidate_slug: string | null;
  candidate_party: string | null;
  opted_out_at: string | null;
  question_summary: string | null;
  segment_type: string;
  text: string;
  timestamp_seconds: number | null;
  youtube_url: string | null;
  topic_summary: string | null;
  source_quote: string | null;
  salience: number;
};

export async function generateMetadata({
  params,
}: {
  params: Promise<{ topic: string }>;
}): Promise<Metadata> {
  const { topic: encodedTopic } = await params;
  const topic = decodeURIComponent(encodedTopic);
  return {
    title: `Hustings excerpts on ${topic} — Jersey 2026 election`,
    description: `Every candidate excerpt from vote.je hustings tagged with "${topic}", grouped by constituency. Display-only — not used in matcher quiz scoring.`,
  };
}

export default async function HustingsTopicPage({
  params,
}: {
  params: Promise<{ topic: string }>;
}) {
  const { topic: encodedTopic } = await params;
  const topic = decodeURIComponent(encodedTopic);

  if (!(TOPICS as readonly string[]).includes(topic)) {
    notFound();
  }

  const rows = (await sql`
    SELECT s.segment_id,
           e.slug AS event_slug,
           e.title AS event_title,
           e.role AS event_role,
           e.constituency AS event_constituency,
           e.transcript_method,
           e.youtube_url,
           s.candidate_id,
           c.full_name AS candidate_name,
           c.vote_je_slug AS candidate_slug,
           c.party AS candidate_party,
           c.opted_out_at,
           s.question_summary,
           s.segment_type,
           s.text,
           s.timestamp_seconds,
           t.summary AS topic_summary,
           t.source_quote,
           t.salience
    FROM hustings_segment_topics t
    JOIN hustings_segments s USING (segment_id)
    JOIN hustings_events e ON e.event_id = s.event_id
    LEFT JOIN candidates c ON c.candidate_id = s.candidate_id
    WHERE t.topic = ${topic}
      AND s.candidate_id IS NOT NULL
      AND c.opted_out_at IS NULL
    ORDER BY e.role, e.constituency, c.full_name, s.position_in_event
  `) as unknown as SegmentRow[];

  // Group by event so each constituency's contributions cluster together.
  const byEvent = new Map<string, SegmentRow[]>();
  for (const r of rows) {
    if (!byEvent.has(r.event_slug)) byEvent.set(r.event_slug, []);
    byEvent.get(r.event_slug)!.push(r);
  }

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <Link
        href="/hustings"
        className="text-sm text-gray-500 dark:text-gray-400 hover:text-red-700 inline-flex items-center gap-1 mb-6"
      >
        &larr; All hustings
      </Link>

      <header className="mb-8">
        <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
          Hustings topic radar
        </p>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100 mb-3">
          {topic}
        </h1>
        <p className="text-gray-600 dark:text-gray-400 max-w-3xl leading-relaxed">
          Every candidate-attributed hustings excerpt tagged with{" "}
          <strong>{topic}</strong>, grouped by event so you can compare what
          candidates standing for the same role said. Hustings content is
          display-only and{" "}
          <Link
            href="/candidates/methodology"
            className="underline hover:text-red-700"
          >
            never used to score the matcher quiz
          </Link>
          .
        </p>
      </header>

      {rows.length === 0 ? (
        <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-lg p-10 text-center text-gray-500 dark:text-gray-400">
          No hustings excerpts tagged with this topic yet.
        </div>
      ) : (
        <div className="space-y-10">
          {[...byEvent.entries()].map(([eventSlug, segs]) => {
            const ev = segs[0];
            return (
              <section key={eventSlug}>
                <header className="mb-4">
                  <Link
                    href={`/hustings/${eventSlug}`}
                    className="block hover:text-red-700"
                  >
                    <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                      {[ev.event_role, ev.event_constituency].filter(Boolean).join(" · ")}
                    </p>
                    <div className="flex items-center gap-2 flex-wrap">
                      <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">
                        {ev.event_title} &rarr;
                      </h2>
                      <TranscriptMethodBadge method={ev.transcript_method} />
                    </div>
                  </Link>
                </header>
                <div className="space-y-4">
                  {segs.map((s) => (
                    <article
                      key={s.segment_id}
                      className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-lg p-4"
                    >
                      <div className="flex items-baseline justify-between gap-3 mb-2 flex-wrap">
                        {s.candidate_slug && s.candidate_name ? (
                          <Link
                            href={`/candidates/${s.candidate_slug}`}
                            className="text-sm font-semibold text-gray-900 dark:text-gray-100 hover:text-red-700"
                          >
                            {s.candidate_name}
                            {s.candidate_party && (
                              <span className="text-xs font-normal text-gray-500 dark:text-gray-400 ml-2">
                                ({s.candidate_party})
                              </span>
                            )}
                          </Link>
                        ) : null}
                        <span className="text-xs text-gray-500 dark:text-gray-400 capitalize">
                          {s.segment_type.replace(/_/g, " ")}
                        </span>
                      </div>
                      {s.question_summary && s.segment_type === "question_answer" && (
                        <p className="text-xs text-gray-500 dark:text-gray-400 italic mb-2 line-clamp-2">
                          Q: {s.question_summary}
                        </p>
                      )}
                      {s.topic_summary && (
                        <p className="text-sm text-gray-800 dark:text-gray-200 mb-2 leading-relaxed">
                          {s.topic_summary}
                        </p>
                      )}
                      {s.source_quote && (
                        <blockquote className="text-sm text-gray-600 dark:text-gray-400 border-l-2 border-gray-200 dark:border-zinc-700 pl-3 italic">
                          &ldquo;{s.source_quote}&rdquo;
                        </blockquote>
                      )}
                      <div className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                        <Link
                          href={`/hustings/${eventSlug}`}
                          className="underline hover:text-red-700"
                        >
                          Read full segment in context &rarr;
                        </Link>
                        {s.timestamp_seconds !== null && s.youtube_url && (
                          <>
                            <span className="mx-2">·</span>
                            <a
                              href={youtubeAt(s.youtube_url, s.timestamp_seconds)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="underline hover:text-red-700"
                            >
                              YouTube &rarr;
                            </a>
                          </>
                        )}
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

function youtubeAt(url: string, seconds: number): string {
  try {
    const u = new URL(url);
    u.searchParams.set("t", String(seconds));
    return u.toString();
  } catch {
    return url;
  }
}
