import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { sql } from "@/lib/db";
import { slugify } from "@/lib/slugify";
import { TrackView } from "@/lib/track-view";
import { TranscriptMethodBadge } from "@/app/hustings/transcript-method-badge";
import { isChatEnabled } from "@/lib/flags";
import { AskBox } from "@/app/ask/ask-box";

type CandidateFull = {
  candidate_id: number;
  vote_je_slug: string;
  profile_url: string;
  full_name: string;
  role: string | null;
  constituency: string | null;
  party: string | null;
  photo_url: string | null;
  email: string | null;
  manifesto_text: string | null;
  manifesto_word_count: number | null;
  enhanced_manifesto_text: string | null;
  enhanced_manifesto_source_url: string | null;
  enhanced_manifesto_source_label: string | null;
  enhanced_manifesto_word_count: number | null;
  enhanced_manifesto_fetched_at: string | null;
  enhanced_manifesto_status: string | null;
  incumbent_member_id: number | null;
  incumbent_canonical_name: string | null;
  incumbent_display_name: string | null;
  scrape_status: string;
  scraped_at: string;
  classified_at: string | null;
  opted_out_at: string | null;
};

const ENHANCED_SOURCE_LABELS: Record<string, string> = {
  personal_site: "Personal site",
  party_page: "Party page",
  party_manifesto: "Party manifesto",
  facebook: "Facebook",
  linkedin: "LinkedIn",
  news_interview: "News interview",
  // Sources written by pipeline/ingest_manual_manifestos.py — keep in sync
  // with MANUAL_SOURCE_LABELS in that script.
  manually_supplied: "Supplied directly",
  social_media_capture: "Social media (archived)",
  printed_handout: "Printed handout (archived)",
  other: "Web source",
};

const MANUAL_SOURCE_LABELS = new Set([
  "manually_supplied",
  "social_media_capture",
  "printed_handout",
]);

function sourceLabelWithFormat(label: string, url: string | null): string {
  const isPdf = !!url && url.toLowerCase().endsWith(".pdf");
  return isPdf ? `${label} (PDF)` : label;
}

type TopicRow = {
  topic: string;
  salience: number;
  summary: string | null;
  source_quote: string | null;
};

type StanceRow = {
  question_id: string;
  stance: string;
  corrected_stance: string | null;
  confidence: number;
  source_quote: string | null;
  statement: string;
  topic: string;
  explainer: string | null;
};

type HustingsTopicTag = {
  topic: string;
  salience: number;
  summary: string | null;
  source_quote: string | null;
};

type HustingsSegmentRow = {
  segment_id: number;
  event_id: number;
  event_slug: string;
  event_title: string;
  event_role: string | null;
  event_constituency: string | null;
  event_date: string | null;
  youtube_url: string | null;
  transcript_method: "hand_cleaned" | "auto_pipeline" | "auto_pipeline_reviewed";
  question_index: number | null;
  question_summary: string | null;
  questioner_name: string | null;
  timestamp_seconds: number | null;
  text: string;
  segment_type: string;
  topics: HustingsTopicTag[] | null;
};

type HustingsQuestionStat = {
  event_id: number;
  question_index: number;
};

async function loadCandidate(slug: string): Promise<CandidateFull | null> {
  // Opted-out candidates still load — we render a minimal "opted out" page
  // for them rather than 404. Their name, role, parish, and party are public
  // States Greffe data, so listing them as standing is appropriate; only
  // their analysis is suppressed.
  const rows = (await sql`
    SELECT c.*,
           m.canonical_name AS incumbent_canonical_name,
           m.display_name AS incumbent_display_name
    FROM candidates c
    LEFT JOIN members m ON m.member_id = c.incumbent_member_id
    WHERE c.vote_je_slug = ${slug}
    LIMIT 1
  `) as unknown as CandidateFull[];
  return rows[0] ?? null;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const c = await loadCandidate(slug);
  if (!c) return {};
  const where = [c.role, c.constituency].filter(Boolean).join(", ");
  return {
    title: `${c.full_name} — Candidate, Jersey 2026 election`,
    description: `${c.full_name}${where ? `, standing for ${where}` : ""}. View their manifesto, policy positions, and stance breakdown.`,
    openGraph: {
      title: c.full_name,
      url: `https://jerseyvotes.org/candidates/${slug}`,
    },
  };
}

export default async function CandidateProfile({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const c = await loadCandidate(slug);
  if (!c) notFound();

  // Opted-out candidates: render a minimal page acknowledging they are
  // standing in the election (public States Greffe fact) but have asked
  // not to be analysed here. Link to their vote.je profile for voters
  // who want to read their published material directly.
  if (c.opted_out_at) {
    return <OptedOutCandidate c={c} />;
  }

  const [topicsAny, stancesAny, hustingsAny, hustingsQAny] = await Promise.all([
    sql`
      SELECT topic, salience, summary, source_quote
      FROM candidate_topics
      WHERE candidate_id = ${c.candidate_id}
      ORDER BY salience DESC
    `,
    sql`
      SELECT cs.question_id, cs.stance, cs.corrected_stance,
             cs.confidence, cs.source_quote,
             cq.statement, cq.topic, cq.explainer
      FROM candidate_stances cs
      JOIN canonical_questions cq ON cq.question_id = cs.question_id
      WHERE cs.candidate_id = ${c.candidate_id}
      ORDER BY cq.topic, cq.sort_order
    `,
    // Hustings segments the candidate spoke (opening / Q&A / closing).
    // Topics joined inline so we render in one pass.
    sql`
      SELECT s.segment_id, s.event_id,
             e.slug AS event_slug, e.title AS event_title,
             e.role AS event_role, e.constituency AS event_constituency,
             e.event_date, e.youtube_url, e.transcript_method,
             s.question_index, s.question_summary, s.questioner_name,
             s.timestamp_seconds, s.text, s.segment_type,
             (
               SELECT COALESCE(json_agg(json_build_object(
                 'topic', t.topic, 'salience', t.salience,
                 'summary', t.summary, 'source_quote', t.source_quote
               ) ORDER BY t.salience DESC), '[]'::json)
               FROM hustings_segment_topics t WHERE t.segment_id = s.segment_id
             ) AS topics
      FROM hustings_segments s
      JOIN hustings_events e ON e.event_id = s.event_id
      WHERE s.candidate_id = ${c.candidate_id}
      ORDER BY e.event_date NULLS LAST, e.slug, s.position_in_event
    `,
    // Every audience question across the events the candidate attended.
    // Used to render greyed-out "did not respond" rows for questions
    // the candidate was on the panel for but didn't answer.
    sql`
      SELECT q.event_id, q.question_index
      FROM hustings_segments q
      WHERE q.segment_type = 'audience_question'
        AND q.event_id IN (
          SELECT DISTINCT event_id FROM hustings_segments
          WHERE candidate_id = ${c.candidate_id}
        )
      ORDER BY q.event_id, q.question_index
    `,
  ]);
  const topics = topicsAny as unknown as TopicRow[];
  const stances = stancesAny as unknown as StanceRow[];
  const hustingsSegments = hustingsAny as unknown as HustingsSegmentRow[];
  const allHustingsQuestions = hustingsQAny as unknown as HustingsQuestionStat[];

  const stancesByTopic = new Map<string, StanceRow[]>();
  for (const s of stances) {
    if (!stancesByTopic.has(s.topic)) stancesByTopic.set(s.topic, []);
    stancesByTopic.get(s.topic)!.push(s);
  }

  const isIncumbent = c.incumbent_member_id !== null;
  const isLowContent = c.scrape_status === "low_content";
  const isClassified = c.classified_at !== null;
  const hasEnhanced =
    c.enhanced_manifesto_status === "found" &&
    !!c.enhanced_manifesto_text &&
    !!c.enhanced_manifesto_source_url;
  const enhancedSourceLabel = hasEnhanced
    ? ENHANCED_SOURCE_LABELS[c.enhanced_manifesto_source_label ?? "other"] ??
      "Web source"
    : null;
  const isManuallySupplied =
    hasEnhanced &&
    !!c.enhanced_manifesto_source_label &&
    MANUAL_SOURCE_LABELS.has(c.enhanced_manifesto_source_label);

  const chatEnabled = await isChatEnabled();

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <TrackView
        event="candidate_profile_viewed"
        params={{
          slug: c.vote_je_slug,
          name: c.full_name,
          role: c.role ?? "",
          is_incumbent: isIncumbent,
          low_content: isLowContent,
        }}
      />
      <Link
        href="/candidates"
        className="text-sm text-gray-500 dark:text-gray-400 hover:text-red-700 inline-flex items-center gap-1 mb-6"
      >
        &larr; All candidates
      </Link>

      {/* Header */}
      <header className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl p-6 mb-6">
        <div className="flex gap-5 items-start">
          <div className="w-24 h-24 flex-shrink-0 rounded-xl overflow-hidden bg-gray-100 dark:bg-zinc-800">
            {c.photo_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={c.photo_url}
                alt={c.full_name}
                className="w-full h-full object-cover"
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-gray-400 text-3xl">
                {c.full_name.charAt(0)}
              </div>
            )}
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-gray-100">
              {c.full_name}
            </h1>
            <p className="text-gray-500 dark:text-gray-400 mt-1">
              {[
                c.role,
                c.constituency ?? (c.role === "Senator" ? "island-wide" : null),
              ]
                .filter(Boolean)
                .join(" — ")}
            </p>
            <div className="flex flex-wrap gap-2 mt-3">
              {c.party && (
                <span className="text-xs bg-gray-100 dark:bg-zinc-800 text-gray-700 dark:text-gray-300 px-2 py-0.5 rounded">
                  {c.party}
                </span>
              )}
              {isIncumbent && c.incumbent_canonical_name && (
                <Link
                  href={`/members/${slugify(c.incumbent_canonical_name)}`}
                  className="text-xs bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300 px-2 py-0.5 rounded hover:underline"
                >
                  Incumbent · see voting record &rarr;
                </Link>
              )}
              {isLowContent && !hasEnhanced && (
                <span className="text-xs bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 px-2 py-0.5 rounded">
                  Short manifesto ({c.manifesto_word_count ?? 0} words)
                </span>
              )}
              {hasEnhanced && (
                <span className="text-xs bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 px-2 py-0.5 rounded">
                  Extended manifesto ({c.enhanced_manifesto_word_count ?? 0} words)
                </span>
              )}
              {isManuallySupplied && (
                <span className="text-xs bg-sky-50 dark:bg-sky-900/30 text-sky-700 dark:text-sky-300 px-2 py-0.5 rounded">
                  Manifesto supplied directly
                </span>
              )}
              {!isClassified && (
                <span className="text-xs bg-gray-100 dark:bg-zinc-800 text-gray-500 dark:text-gray-400 px-2 py-0.5 rounded">
                  Not yet classified
                </span>
              )}
            </div>
            <div className="mt-4 text-xs text-gray-500 dark:text-gray-400">
              <a
                href={c.profile_url}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-red-700"
              >
                Source profile on vote.je &rarr;
              </a>
              {hasEnhanced && c.enhanced_manifesto_source_url && (
                <>
                  <span className="mx-2">·</span>
                  <a
                    href={c.enhanced_manifesto_source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:text-red-700"
                  >
                    {enhancedSourceLabel} (extended) &rarr;
                  </a>
                </>
              )}
              {c.email && (
                <>
                  <span className="mx-2">·</span>
                  <a href={`mailto:${c.email}`} className="hover:text-red-700">
                    {c.email}
                  </a>
                </>
              )}
            </div>
          </div>
        </div>
      </header>

      {chatEnabled && (
        <div className="mb-6">
          {/* No pre-populated questions here: suggesting a specific topic on a
              candidate's own page could read as editorial bias. The placeholder
              guides without steering. */}
          <AskBox
            title={`Ask about ${c.full_name}`}
            subtitle="Get answers drawn from this candidate's manifesto and hustings appearances, with sources."
            scope={{ candidateSlug: c.vote_je_slug }}
            placeholder={`Ask about ${c.full_name}…`}
          />
        </div>
      )}

      {/* Topic coverage */}
      {topics.length > 0 && (
        <section className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl p-6 mb-6">
          <h2 className="text-xl font-bold mb-1 text-gray-900 dark:text-gray-100">
            Topics this manifesto addresses
          </h2>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
            Salience is an estimate of how much of the manifesto is devoted to each topic.{" "}
            <Link href="/candidates/methodology" className="underline">
              How this is calculated
            </Link>
          </p>
          <div className="space-y-3">
            {topics.map((t) => (
              <div
                key={t.topic}
                className="border border-gray-100 dark:border-zinc-800 rounded-lg p-3"
              >
                <div className="flex items-center justify-between mb-1.5">
                  <p className="font-medium text-gray-900 dark:text-gray-100">{t.topic}</p>
                  <span className="text-xs text-gray-500 dark:text-gray-400 tabular-nums">
                    {Math.round(t.salience * 100)}% salience
                  </span>
                </div>
                <div className="h-1.5 bg-gray-100 dark:bg-zinc-800 rounded-full overflow-hidden mb-2">
                  <div
                    className="h-full bg-red-600"
                    style={{ width: `${Math.min(100, t.salience * 100)}%` }}
                  />
                </div>
                {t.summary && (
                  <p className="text-sm text-gray-700 dark:text-gray-300">{t.summary}</p>
                )}
                {t.source_quote && (
                  <blockquote className="mt-2 pl-3 border-l-2 border-gray-200 dark:border-zinc-700 text-xs text-gray-500 dark:text-gray-400 italic">
                    &ldquo;{t.source_quote}&rdquo;
                  </blockquote>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Stance grid */}
      {stances.length > 0 && (
        <section className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl p-6 mb-6">
          <h2 className="text-xl font-bold mb-1 text-gray-900 dark:text-gray-100">
            Positions on policy statements
          </h2>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
            Each stance is extracted from the manifesto with a verbatim supporting quote.
            &ldquo;Not addressed&rdquo; means the manifesto did not take a position.
          </p>
          <div className="space-y-5">
            {[...stancesByTopic.entries()].map(([topic, rows]) => (
              <div key={topic}>
                <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2 uppercase tracking-wide">
                  {topic}
                </h3>
                <div className="space-y-3">
                  {rows.map((s) => {
                    const stance = (s.corrected_stance ?? s.stance) as
                      | "agree"
                      | "disagree"
                      | "neutral"
                      | "not_addressed";
                    return (
                      <div
                        key={s.question_id}
                        className="border border-gray-100 dark:border-zinc-800 rounded-lg p-3"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <p className="text-sm text-gray-800 dark:text-gray-200 flex-1">
                            {s.statement}
                          </p>
                          <StanceBadge stance={stance} />
                        </div>
                        {s.source_quote && stance !== "not_addressed" && (
                          <blockquote className="mt-2 pl-3 border-l-2 border-gray-200 dark:border-zinc-700 text-xs text-gray-500 dark:text-gray-400 italic">
                            &ldquo;{s.source_quote}&rdquo;
                          </blockquote>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Hustings appearances. Spoken record from vote.je hustings videos —
          displayed only, never blended into the matcher quiz (see methodology
          page for the trust boundary). */}
      {hustingsSegments.length > 0 && (
        <HustingsAppearancesSection
          segments={hustingsSegments}
          allQuestions={allHustingsQuestions}
          candidateName={c.full_name}
        />
      )}

      {/* Manifesto sources. We link to the originals rather than embedding
          the text — PDFs and party pages format much better in their native
          form, and the source quotes in the Topics + Policy positions
          sections above already give readers verbatim excerpts to verify
          our analysis against. */}
      {(c.enhanced_manifesto_text || c.manifesto_text) && (
        <section className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl p-6 mb-6">
          <h2 className="text-xl font-bold mb-3 text-gray-900 dark:text-gray-100">
            Manifesto sources
          </h2>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-5 leading-relaxed">
            The topic and stance analysis above is derived from the text of
            the source manifesto{hasEnhanced ? "s" : ""} below. We link to the
            original{hasEnhanced ? "s" : ""} rather than embedding the
            text — they format better in their native form, and the source
            quotes attached to each topic and policy position above already
            give you verbatim excerpts to check our reading against.
          </p>

          <ul className="space-y-3">
            {hasEnhanced && c.enhanced_manifesto_source_url && (
              <li className="bg-gray-50 dark:bg-zinc-950 border border-gray-200 dark:border-zinc-800 rounded-lg p-4">
                <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
                  Used for analysis ·{" "}
                  {sourceLabelWithFormat(
                    enhancedSourceLabel ?? "Web source",
                    c.enhanced_manifesto_source_url,
                  )}
                </p>
                <a
                  href={c.enhanced_manifesto_source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-red-700 underline hover:no-underline font-medium break-all"
                >
                  {c.enhanced_manifesto_source_url}
                </a>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  {(c.enhanced_manifesto_word_count ?? 0).toLocaleString()}{" "}
                  words
                  {c.enhanced_manifesto_fetched_at && (
                    <>
                      {isManuallySupplied ? " · added on " : " · fetched on "}
                      {new Date(
                        c.enhanced_manifesto_fetched_at,
                      ).toLocaleDateString("en-GB", {
                        day: "numeric",
                        month: "long",
                        year: "numeric",
                      })}
                    </>
                  )}
                </p>
                {isManuallySupplied && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-2 leading-relaxed">
                    This candidate doesn&rsquo;t publish a manifesto online in a
                    form we could analyse, so the source documents (Word file,
                    PDF, photo, or social-media screenshot) were supplied to us
                    and committed to the public{" "}
                    <a
                      href={c.enhanced_manifesto_source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline hover:text-red-700"
                    >
                      Jerseyvotes.org repo
                    </a>{" "}
                    so anyone can audit them.
                  </p>
                )}
              </li>
            )}

            {c.manifesto_text && (
              <li className="bg-gray-50 dark:bg-zinc-950 border border-gray-200 dark:border-zinc-800 rounded-lg p-4">
                <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
                  {hasEnhanced
                    ? "Also referenced · vote.je profile"
                    : "Used for analysis · vote.je profile"}
                </p>
                <a
                  href={c.profile_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-red-700 underline hover:no-underline font-medium break-all"
                >
                  {c.profile_url}
                </a>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  {(c.manifesto_word_count ?? 0).toLocaleString()} words ·
                  scraped on{" "}
                  {new Date(c.scraped_at).toLocaleDateString("en-GB", {
                    day: "numeric",
                    month: "long",
                    year: "numeric",
                  })}
                </p>
              </li>
            )}
          </ul>
        </section>
      )}

      <p className="text-center text-sm text-gray-500 dark:text-gray-400">
        Spotted an error?{" "}
        <a
          href={`mailto:gus@helix.je?subject=${encodeURIComponent(
            `Candidate correction: ${c.full_name}`
          )}&body=${encodeURIComponent(
            `Profile: https://jerseyvotes.org/candidates/${c.vote_je_slug}\n\nWhat's wrong (and what should it say)?\n\n`
          )}`}
          className="underline hover:text-red-700"
        >
          Report it
        </a>{" "}
        — we update profiles within 24 hours.
      </p>
    </div>
  );
}

function OptedOutCandidate({ c }: { c: CandidateFull }) {
  const where = [c.role, c.constituency].filter(Boolean).join(" · ");
  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <Link
        href="/candidates"
        className="inline-flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 hover:text-red-700 mb-6"
      >
        &larr; All candidates
      </Link>

      <header className="flex gap-5 items-start mb-8">
        {c.photo_url && (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={c.photo_url}
            alt={c.full_name}
            className="w-20 h-20 sm:w-24 sm:h-24 rounded-full object-cover grayscale opacity-80 flex-shrink-0"
          />
        )}
        <div className="min-w-0">
          <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-gray-100 mb-1">
            {c.full_name}
          </h1>
          {where && (
            <p className="text-gray-500 dark:text-gray-400 text-sm sm:text-base">
              {where}
              {c.party ? ` · ${c.party}` : ""}
            </p>
          )}
        </div>
      </header>

      <div className="bg-gray-50 dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl p-6 mb-6">
        <p className="text-gray-700 dark:text-gray-300 mb-4 leading-relaxed">
          <strong className="text-gray-900 dark:text-gray-100">
            {c.full_name}
          </strong>{" "}
          is standing in the 2026 Jersey election but has opted out of
          jerseyvotes.org&rsquo;s topic and policy-position analysis. To read
          their own published material, see their vote.je profile or any
          other channels they publish on.
        </p>
        <a
          href={c.profile_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 px-4 py-2 bg-red-700 text-white rounded-md hover:bg-red-800 font-medium text-sm"
        >
          View vote.je profile
          <svg
            className="w-3.5 h-3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M14 5l7 7m0 0l-7 7m7-7H3"
            />
          </svg>
        </a>
      </div>

      <p className="text-xs text-gray-500 dark:text-gray-400">
        Candidates can opt out of analysis at any time via the private
        review link they receive. See the{" "}
        <Link
          href="/candidates/methodology"
          className="underline hover:text-red-700"
        >
          methodology page
        </Link>
        {" "}for details.
      </p>
    </div>
  );
}

function HustingsAppearancesSection({
  segments,
  allQuestions,
  candidateName,
}: {
  segments: HustingsSegmentRow[];
  allQuestions: HustingsQuestionStat[];
  candidateName: string;
}) {
  // Group segments by event.
  const byEvent = new Map<number, HustingsSegmentRow[]>();
  for (const s of segments) {
    if (!byEvent.has(s.event_id)) byEvent.set(s.event_id, []);
    byEvent.get(s.event_id)!.push(s);
  }

  // For each event, build a Set of question_indexes the candidate answered,
  // and the total questions on the panel.
  const eventQuestionTotals = new Map<number, number>();
  for (const q of allQuestions) {
    eventQuestionTotals.set(
      q.event_id,
      (eventQuestionTotals.get(q.event_id) ?? 0) + 1,
    );
  }

  return (
    <section className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl p-6 mb-6">
      <h2 className="text-xl font-bold mb-1 text-gray-900 dark:text-gray-100">
        Hustings appearances
      </h2>
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-5 leading-relaxed">
        Verbatim excerpts from vote.je hustings videos where {candidateName}{" "}
        spoke, tagged against the same 16-topic taxonomy.{" "}
        <Link
          href="/candidates/methodology"
          className="underline hover:text-red-700"
        >
          Display only — not used to score the matcher quiz
        </Link>
        .
      </p>

      <div className="space-y-8">
        {[...byEvent.entries()].map(([eventId, segs]) => {
          const ev = segs[0];
          const totalQuestions = eventQuestionTotals.get(eventId) ?? 0;
          const answeredQuestionIdx = new Set(
            segs
              .filter((s) => s.segment_type === "question_answer" && s.question_index !== null)
              .map((s) => s.question_index as number),
          );
          // Multiple DB rows can exist per (candidate, question_index)
          // when pyannote split one continuous answer at silence points.
          // Group those rows by question_index so the page renders one
          // merged block per answer instead of 3-5 fragments.
          const answers = segs
            .filter((s) => s.segment_type === "question_answer")
            .sort((a, b) =>
              (a.question_index ?? 0) - (b.question_index ?? 0) ||
              (a.segment_id - b.segment_id),
            );
          const answersByQ = new Map<number, HustingsSegmentRow[]>();
          for (const a of answers) {
            if (a.question_index === null) continue;
            const arr = answersByQ.get(a.question_index) ?? [];
            arr.push(a);
            answersByQ.set(a.question_index, arr);
          }
          // Multiple opening_speech rows for the same speaker also happen
          // — collect them all and render as one merged block.
          const openings = segs.filter((s) => s.segment_type === "opening_speech");
          const closings = segs.filter((s) => s.segment_type === "closing_speech");

          // Build a list of every question in the event in order, marking
          // the ones this candidate didn't answer as "did not respond".
          const eventQuestions = allQuestions
            .filter((q) => q.event_id === eventId)
            .sort((a, b) => a.question_index - b.question_index)
            .map((q) => q.question_index);

          return (
            <article key={eventId}>
              <header className="mb-4">
                <Link
                  href={`/hustings/${ev.event_slug}`}
                  className="block hover:text-red-700"
                >
                  <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                    {[ev.event_role, ev.event_constituency].filter(Boolean).join(" · ")}
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
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="text-lg font-bold text-gray-900 dark:text-gray-100">
                      {ev.event_title} &rarr;
                    </h3>
                    <TranscriptMethodBadge method={ev.transcript_method} />
                  </div>
                </Link>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Answered {answeredQuestionIdx.size} of {totalQuestions} audience
                  question{totalQuestions === 1 ? "" : "s"}
                </p>
              </header>

              {openings.length > 0 && (
                <div className="mb-4">
                  <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
                    Opening speech
                  </p>
                  <HustingsSegmentRender segs={openings} />
                </div>
              )}

              {eventQuestions.length > 0 && (
                <div>
                  <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
                    Audience questions
                  </p>
                  <div className="space-y-3">
                    {eventQuestions.map((qIdx) => {
                      const ansGroup = answersByQ.get(qIdx) ?? [];
                      if (ansGroup.length > 0) {
                        return (
                          <HustingsSegmentRender
                            key={qIdx}
                            segs={ansGroup}
                            showQuestion
                          />
                        );
                      }
                      return (
                        <div
                          key={qIdx}
                          className="border border-dashed border-gray-200 dark:border-zinc-800 rounded-lg px-4 py-2 text-xs text-gray-400 dark:text-gray-600 italic"
                        >
                          Question {qIdx}: did not respond
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {closings.length > 0 && (
                <div className="mt-4">
                  <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
                    Closing remarks
                  </p>
                  <HustingsSegmentRender segs={closings} />
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function HustingsSegmentRender({
  segs,
  showQuestion = false,
}: {
  segs: HustingsSegmentRow[] | HustingsSegmentRow;
  showQuestion?: boolean;
}) {
  // Normalise: a single segment or an array — when pyannote splits one
  // continuous answer at silence points we end up with multiple DB rows
  // per (candidate, question) which we want to render as ONE block.
  const list = Array.isArray(segs) ? segs : [segs];
  if (list.length === 0) return null;
  const first = list[0];

  // Concatenate text. Most readable when segments are joined with a
  // single space — pyannote splits don't carry punctuation.
  const text = list.map((s) => s.text).join(" ").replace(/\s+/g, " ").trim();

  // Dedupe topic chips by topic name. Take the highest salience entry
  // when the same topic appears across multiple segments.
  const topicMap = new Map<string, HustingsTopicTag>();
  for (const s of list) {
    for (const t of s.topics ?? []) {
      const existing = topicMap.get(t.topic);
      if (!existing || t.salience > existing.salience) {
        topicMap.set(t.topic, t);
      }
    }
  }
  const topics = Array.from(topicMap.values()).sort((a, b) => b.salience - a.salience);

  const ytLink =
    first.timestamp_seconds !== null && first.youtube_url
      ? youtubeAtTime(first.youtube_url, first.timestamp_seconds)
      : null;

  return (
    <div className="bg-gray-50 dark:bg-zinc-950 border border-gray-100 dark:border-zinc-800 rounded-lg p-4">
      {showQuestion && first.question_summary && (
        <div className="mb-3">
          <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
            Question{first.question_index !== null ? ` ${first.question_index}` : ""}
            {first.questioner_name && ` · ${first.questioner_name}`}
          </p>
          <blockquote className="text-xs text-gray-600 dark:text-gray-400 italic border-l-2 border-gray-200 dark:border-zinc-700 pl-2 leading-relaxed">
            {first.question_summary}
          </blockquote>
        </div>
      )}
      <p className="text-sm text-gray-800 dark:text-gray-200 leading-relaxed whitespace-pre-wrap">
        {text}
      </p>
      {(topics.length > 0 || ytLink) && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
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
          {ytLink && (
            <a
              href={ytLink}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-gray-500 dark:text-gray-400 hover:text-red-700 underline ml-auto"
            >
              Watch on YouTube &rarr;
            </a>
          )}
        </div>
      )}
    </div>
  );
}

function youtubeAtTime(url: string, seconds: number): string {
  try {
    const u = new URL(url);
    u.searchParams.set("t", String(seconds));
    return u.toString();
  } catch {
    return url;
  }
}

function StanceBadge({
  stance,
}: {
  stance: "agree" | "disagree" | "neutral" | "not_addressed";
}) {
  const styles: Record<string, string> = {
    agree: "bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-300",
    disagree: "bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300",
    neutral: "bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300",
    not_addressed: "bg-gray-50 dark:bg-zinc-800 text-gray-500 dark:text-gray-400",
  };
  const labels: Record<string, string> = {
    agree: "Agree",
    disagree: "Disagree",
    neutral: "Neutral",
    not_addressed: "Not addressed",
  };
  return (
    <span
      className={`text-xs font-medium px-2 py-0.5 rounded whitespace-nowrap ${styles[stance]}`}
    >
      {labels[stance]}
    </span>
  );
}
