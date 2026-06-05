import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { sql } from "@/lib/db";
import { TranscriptMethodBadge, type TranscriptMethod } from "../transcript-method-badge";
import { isChatEnabled } from "@/lib/flags";
import { AskBox } from "@/app/ask/ask-box";

type EventRow = {
  event_id: number;
  slug: string;
  title: string;
  role: string | null;
  constituency: string | null;
  event_date: string | null;
  youtube_url: string | null;
  transcript_source_url: string;
  transcript_method: TranscriptMethod;
};

type CandidateRow = {
  candidate_id: number;
  full_name: string;
  vote_je_slug: string;
  party: string | null;
  photo_url: string | null;
  opted_out_at: string | null;
};

type SegmentRow = {
  segment_id: number;
  candidate_id: number | null;
  speaker_name_raw: string;
  segment_type: string;
  question_index: number | null;
  question_summary: string | null;
  question_summary_source: string | null;
  questioner_name: string | null;
  timestamp_seconds: number | null;
  text: string;
  text_youtube_asr: string | null;
  position_in_event: number;
  topics: { topic: string; salience: number; summary: string | null; source_quote: string | null }[] | null;
};

export async function generateMetadata({
  params,
}: {
  params: Promise<{ event: string }>;
}): Promise<Metadata> {
  const { event } = await params;
  const rows = (await sql`
    SELECT title, role, constituency FROM hustings_events WHERE slug = ${event} LIMIT 1
  `) as unknown as { title: string; role: string | null; constituency: string | null }[];
  if (!rows[0]) return {};
  const ev = rows[0];
  return {
    title: `${ev.title} — Hustings transcript`,
    description: `Transcript of the ${ev.title} hustings, with every candidate's answer to every audience question.`,
  };
}

export default async function EventPage({
  params,
}: {
  params: Promise<{ event: string }>;
}) {
  const { event } = await params;
  const eventRows = (await sql`
    SELECT event_id, slug, title, role, constituency, event_date,
           youtube_url, transcript_source_url, transcript_method
    FROM hustings_events WHERE slug = ${event} LIMIT 1
  `) as unknown as EventRow[];
  const ev = eventRows[0];
  if (!ev) notFound();

  // Candidates in the event roster, in the order they appear by position.
  const candidates = (await sql`
    SELECT DISTINCT c.candidate_id, c.full_name, c.vote_je_slug, c.party,
                    c.photo_url, c.opted_out_at,
                    MIN(s.position_in_event) AS first_position
    FROM hustings_segments s
    JOIN candidates c ON c.candidate_id = s.candidate_id
    WHERE s.event_id = ${ev.event_id}
    GROUP BY c.candidate_id, c.full_name, c.vote_je_slug, c.party,
             c.photo_url, c.opted_out_at
    ORDER BY MIN(s.position_in_event)
  `) as unknown as (CandidateRow & { first_position: number })[];

  // All segments with their topic tags inlined as a JSON array per row.
  const segments = (await sql`
    SELECT s.segment_id, s.candidate_id, s.speaker_name_raw, s.segment_type,
           s.question_index, s.question_summary, s.question_summary_source,
           s.questioner_name, s.timestamp_seconds, s.text, s.text_youtube_asr,
           s.position_in_event,
           (
             SELECT COALESCE(json_agg(json_build_object(
               'topic', t.topic, 'salience', t.salience,
               'summary', t.summary, 'source_quote', t.source_quote
             ) ORDER BY t.salience DESC), '[]'::json)
             FROM hustings_segment_topics t WHERE t.segment_id = s.segment_id
           ) AS topics
    FROM hustings_segments s
    WHERE s.event_id = ${ev.event_id}
    ORDER BY s.position_in_event
  `) as unknown as SegmentRow[];

  const opening = segments.filter((s) => s.segment_type === "opening_speech");
  const closing = segments.filter((s) => s.segment_type === "closing_speech");
  const questions = segments.filter((s) => s.segment_type === "audience_question");
  const answers = segments.filter((s) => s.segment_type === "question_answer");
  const moderatorSegs = segments.filter((s) => s.segment_type === "moderator");

  // Group answers by question_index.
  const answersByQuestion = new Map<number, SegmentRow[]>();
  for (const a of answers) {
    if (a.question_index === null) continue;
    if (!answersByQuestion.has(a.question_index))
      answersByQuestion.set(a.question_index, []);
    answersByQuestion.get(a.question_index)!.push(a);
  }

  // For each question, build a "did this candidate answer" map so we can
  // render greyed-out "did not respond" rows for everyone on the panel
  // who didn't speak on this question. Senator-sized panels (>8) skip
  // the non-response rows to keep the page readable.
  const largePanel = candidates.length > 8;

  const chatEnabled = await isChatEnabled();

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <Link
        href="/hustings"
        className="text-sm text-gray-500 dark:text-gray-400 hover:text-red-700 inline-flex items-center gap-1 mb-6"
      >
        &larr; All hustings
      </Link>

      <header className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl p-6 mb-6">
        <div className="flex items-start justify-between gap-3 mb-1">
          <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-gray-100">
            {ev.title}
          </h1>
          <TranscriptMethodBadge method={ev.transcript_method} />
        </div>
        <p className="text-gray-500 dark:text-gray-400">
          {[ev.role, ev.constituency].filter(Boolean).join(" · ")}
          {ev.event_date && (
            <>
              {" · "}
              {new Date(ev.event_date).toLocaleDateString("en-GB", {
                day: "numeric",
                month: "long",
                year: "numeric",
              })}
            </>
          )}
        </p>
        {ev.transcript_method === "auto_pipeline" && (
          <p className="mt-3 text-xs text-amber-700 dark:text-amber-300 leading-relaxed bg-amber-50 dark:bg-amber-900/20 border-l-2 border-amber-400 pl-3 py-1.5">
            This transcript was produced by an automated pipeline — YouTube
            audio transcribed with Whisper, speakers separated with pyannote,
            audience-question summaries written by Claude. It has not been
            human-reviewed. Expect occasional STT artefacts in candidate
            answers (dropped {`"I"`} pronouns, mis-attributed speakers) and
            the occasional unmappable audience speaker shown as{" "}
            {`"Audience member"`}. Each audience question&apos;s headline is
            an LLM summary — click {`"As captured from audio"`} beneath it to
            see the verbatim YouTube caption. The YouTube video is always the
            ground truth.
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-3 text-xs text-gray-500 dark:text-gray-400">
          {ev.youtube_url && (
            <a
              href={ev.youtube_url}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-red-700 underline"
            >
              Watch on YouTube &rarr;
            </a>
          )}
          <a
            href={ev.transcript_source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-red-700 underline"
          >
            Audit transcript on GitHub &rarr;
          </a>
        </div>
        <p className="mt-4 text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
          Display-only material. Hustings excerpts are{" "}
          <Link
            href="/candidates/methodology"
            className="underline hover:text-red-700"
          >
            never used to score the matcher quiz
          </Link>
          . Candidates can email gus@helix.je to dispute or remove any segment.
        </p>
      </header>

      {/* Candidates on the panel */}
      <section className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl p-6 mb-6">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 uppercase tracking-wide">
          Candidates on the panel
        </h2>
        <div className="flex flex-wrap gap-2">
          {candidates.map((c) => (
            <Link
              key={c.candidate_id}
              href={`/candidates/${c.vote_je_slug}`}
              className="inline-flex items-center gap-2 bg-gray-50 dark:bg-zinc-950 border border-gray-200 dark:border-zinc-800 rounded-full pl-1 pr-3 py-1 hover:border-red-300 transition-colors"
            >
              {c.photo_url ? (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={c.photo_url}
                  alt={c.full_name}
                  className="w-6 h-6 rounded-full object-cover"
                />
              ) : (
                <div className="w-6 h-6 rounded-full bg-gray-200 dark:bg-zinc-700" />
              )}
              <span className="text-sm text-gray-900 dark:text-gray-100">
                {c.full_name}
              </span>
              {c.party && (
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  ({c.party})
                </span>
              )}
            </Link>
          ))}
        </div>
      </section>

      {chatEnabled && (
        <div className="mb-6">
          <AskBox
            title="Ask about this hustings"
            subtitle="Get answers drawn from what candidates said at this hustings, with sources."
            scope={{ eventSlug: ev.slug }}
            placeholder="Ask about this hustings…"
            suggestions={[
              "What was said about housing?",
              "Where did candidates disagree?",
            ]}
          />
        </div>
      )}

      {/* Opening speeches */}
      {opening.length > 0 && (
        <section className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl p-6 mb-6">
          <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-1">
            Opening speeches
          </h2>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
            Each candidate&rsquo;s prepared opening statement, in the order they spoke.
          </p>
          <div className="space-y-4">
            {(() => {
              // Group opening_speech rows by candidate so pyannote-split
              // openings render as one block per candidate.
              const byCand = new Map<number | null, SegmentRow[]>();
              for (const s of opening) {
                const arr = byCand.get(s.candidate_id) ?? [];
                arr.push(s);
                byCand.set(s.candidate_id, arr);
              }
              return [...byCand.entries()].map(([candId, group]) => (
                <SegmentBlock
                  key={candId ?? group[0].segment_id}
                  segs={group}
                  candidates={candidates}
                  youtubeUrl={ev.youtube_url}
                />
              ));
            })()}
          </div>
        </section>
      )}

      {/* Audience Q&A */}
      {questions.length > 0 && (
        <section className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl p-6 mb-6">
          <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-1">
            Audience Q&amp;A
          </h2>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
            Every audience question and every candidate&rsquo;s verbatim
            answer.{" "}
            {largePanel
              ? "Candidates who didn't answer a given question are omitted (large panel)."
              : "Candidates who didn't answer a given question are shown as greyed-out rows so silence is distinguishable from absence."}
          </p>
          <div className="space-y-8">
            {questions.map((q, idx) => {
              const answersForQ = q.question_index !== null
                ? answersByQuestion.get(q.question_index) ?? []
                : [];
              const answeredIds = new Set(
                answersForQ.map((a) => a.candidate_id).filter((id): id is number => id !== null),
              );
              const nonResponders = largePanel
                ? []
                : candidates.filter((c) => !answeredIds.has(c.candidate_id));
              const displayName = cleanQuestionerName(q.questioner_name);
              const headline = q.question_summary?.trim() || q.text;
              const isSynthesised = q.question_summary_source === "llm_synthesised"
                && !!q.question_summary?.trim();
              const verbatim = (q.text_youtube_asr || q.text || "").trim();
              return (
                <article key={q.segment_id}>
                  <header className="mb-3">
                    <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
                      Question {idx + 1}
                      {displayName && ` · ${displayName}`}
                      {q.timestamp_seconds !== null && ev.youtube_url && (
                        <>
                          {" · "}
                          <a
                            href={youtubeAt(ev.youtube_url, q.timestamp_seconds)}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="underline hover:text-red-700"
                          >
                            {formatTime(q.timestamp_seconds)}
                          </a>
                        </>
                      )}
                    </p>
                    <blockquote className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed border-l-4 border-gray-200 dark:border-zinc-700 pl-3 italic">
                      {headline}
                    </blockquote>
                    {isSynthesised && verbatim && verbatim !== headline && (
                      <details className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                        <summary className="cursor-pointer hover:text-red-700 select-none">
                          As captured from audio
                        </summary>
                        <p className="mt-1 pl-3 border-l-2 border-gray-100 dark:border-zinc-800 leading-relaxed">
                          {verbatim}
                        </p>
                      </details>
                    )}
                  </header>
                  <div className="space-y-3">
                    {(() => {
                      // Group answers by candidate so pyannote-split
                      // fragments render as one block per candidate.
                      const byCand = new Map<number | null, SegmentRow[]>();
                      for (const a of answersForQ) {
                        const k = a.candidate_id;
                        const arr = byCand.get(k) ?? [];
                        arr.push(a);
                        byCand.set(k, arr);
                      }
                      return [...byCand.entries()].map(([candId, group]) => (
                        <SegmentBlock
                          key={candId ?? group[0].segment_id}
                          segs={group}
                          candidates={candidates}
                          youtubeUrl={ev.youtube_url}
                        />
                      ));
                    })()}
                    {nonResponders.map((c) => (
                      <DidNotRespondRow key={c.candidate_id} c={c} />
                    ))}
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}

      {/* Closing speeches */}
      {closing.length > 0 && (
        <section className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl p-6 mb-6">
          <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-4">
            Closing remarks
          </h2>
          <div className="space-y-4">
            {(() => {
              const byCand = new Map<number | null, SegmentRow[]>();
              for (const s of closing) {
                const arr = byCand.get(s.candidate_id) ?? [];
                arr.push(s);
                byCand.set(s.candidate_id, arr);
              }
              return [...byCand.entries()].map(([candId, group]) => (
                <SegmentBlock
                  key={candId ?? group[0].segment_id}
                  segs={group}
                  candidates={candidates}
                  youtubeUrl={ev.youtube_url}
                />
              ));
            })()}
          </div>
        </section>
      )}

      <p className="text-center text-xs text-gray-500 dark:text-gray-400 mt-8">
        Transcript curated by jerseyvotes.org. Spotted a mis-attribution? Email{" "}
        <a
          href={`mailto:gus@helix.je?subject=${encodeURIComponent(
            `Hustings correction: ${ev.title}`,
          )}`}
          className="underline hover:text-red-700"
        >
          gus@helix.je
        </a>
        {" "}— corrections processed within 24 hours.
        {/* eslint-disable-next-line @typescript-eslint/no-unused-vars */}
        {moderatorSegs.length > 0 ? "" : ""}
      </p>
    </div>
  );
}

function SegmentBlock({
  segs,
  candidates,
  youtubeUrl,
}: {
  segs: SegmentRow[];
  candidates: (CandidateRow & { first_position: number })[];
  youtubeUrl: string | null;
}) {
  if (segs.length === 0) return null;
  const first = segs[0];
  const cand = candidates.find((c) => c.candidate_id === first.candidate_id);
  const isOptedOut = cand?.opted_out_at !== null && cand?.opted_out_at !== undefined;

  // Merge text + dedupe topic chips across the grouped segments — see
  // the same logic in candidates/[slug]/page.tsx for the rationale.
  const text = segs.map((s) => s.text).join(" ").replace(/\s+/g, " ").trim();
  const topicMap = new Map<string, NonNullable<SegmentRow["topics"]>[number]>();
  for (const s of segs) {
    for (const t of s.topics ?? []) {
      const ex = topicMap.get(t.topic);
      if (!ex || t.salience > ex.salience) topicMap.set(t.topic, t);
    }
  }
  const topics = Array.from(topicMap.values()).sort((a, b) => b.salience - a.salience);

  return (
    <div className="bg-gray-50 dark:bg-zinc-950 border border-gray-100 dark:border-zinc-800 rounded-lg p-4">
      <div className="flex items-baseline justify-between gap-3 mb-2 flex-wrap">
        {cand ? (
          isOptedOut ? (
            <p className="text-sm font-semibold text-gray-500 dark:text-gray-400 italic">
              {cand.full_name} (opted out of analysis)
            </p>
          ) : (
            <Link
              href={`/candidates/${cand.vote_je_slug}`}
              className="text-sm font-semibold text-gray-900 dark:text-gray-100 hover:text-red-700"
            >
              {cand.full_name}
              {cand.party && (
                <span className="text-xs font-normal text-gray-500 dark:text-gray-400 ml-2">
                  ({cand.party})
                </span>
              )}
            </Link>
          )
        ) : (
          <p className="text-sm font-semibold text-gray-700 dark:text-gray-300">
            {first.speaker_name_raw}
          </p>
        )}
        {first.timestamp_seconds !== null && youtubeUrl && (
          <a
            href={youtubeAt(youtubeUrl, first.timestamp_seconds)}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-gray-500 dark:text-gray-400 hover:text-red-700 underline tabular-nums"
          >
            {formatTime(first.timestamp_seconds)}
          </a>
        )}
      </div>
      {isOptedOut ? (
        <p className="text-sm text-gray-500 dark:text-gray-400 italic">
          This candidate has opted out of analysis on jerseyvotes.org.
        </p>
      ) : (
        <>
          <p className="text-sm text-gray-800 dark:text-gray-200 leading-relaxed whitespace-pre-wrap">
            {text}
          </p>
          {topics.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {topics.map((t) => (
                <Link
                  key={t.topic}
                  href={`/hustings/topics/${encodeURIComponent(t.topic)}`}
                  className="text-xs text-gray-600 dark:text-gray-300 bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 px-2 py-0.5 rounded hover:border-red-300 hover:text-red-700"
                  title={t.summary ?? undefined}
                >
                  {t.topic}
                </Link>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function DidNotRespondRow({
  c,
}: {
  c: CandidateRow & { first_position: number };
}) {
  return (
    <div className="bg-gray-50 dark:bg-zinc-950 border border-dashed border-gray-200 dark:border-zinc-800 rounded-lg px-4 py-2 flex items-center justify-between">
      <Link
        href={`/candidates/${c.vote_je_slug}`}
        className="text-sm text-gray-500 dark:text-gray-500 hover:text-red-700"
      >
        {c.full_name}
      </Link>
      <span className="text-xs text-gray-400 dark:text-gray-600 italic">
        Did not respond
      </span>
    </div>
  );
}

function cleanQuestionerName(raw: string | null): string | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  // Diarisation labels like <SPEAKER_07> shouldn't reach the UI — when the
  // identify pass couldn't map the audience speaker to a person, fall back
  // to the generic label.
  if (/^<SPEAKER_\d+>$/i.test(trimmed)) return "Audience member";
  return trimmed;
}

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0)
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function youtubeAt(url: string, seconds: number): string {
  // Append ?t=<seconds> (or &t=<seconds>) so the YouTube player starts at
  // the right point. Works for watch?v= and youtu.be/ URLs.
  try {
    const u = new URL(url);
    u.searchParams.set("t", String(seconds));
    return u.toString();
  } catch {
    return url;
  }
}
