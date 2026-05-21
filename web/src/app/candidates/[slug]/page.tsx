import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { sql } from "@/lib/db";
import { slugify } from "@/lib/slugify";
import { TrackView } from "@/lib/track-view";

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
};

const ENHANCED_SOURCE_LABELS: Record<string, string> = {
  personal_site: "Personal site",
  party_page: "Party page",
  facebook: "Facebook",
  linkedin: "LinkedIn",
  news_interview: "News interview",
  other: "Web source",
};

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

async function loadCandidate(slug: string): Promise<CandidateFull | null> {
  const rows = (await sql`
    SELECT c.*,
           m.canonical_name AS incumbent_canonical_name,
           m.display_name AS incumbent_display_name
    FROM candidates c
    LEFT JOIN members m ON m.member_id = c.incumbent_member_id
    WHERE c.vote_je_slug = ${slug}
      AND c.opted_out_at IS NULL
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

  const [topicsAny, stancesAny] = await Promise.all([
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
  ]);
  const topics = topicsAny as unknown as TopicRow[];
  const stances = stancesAny as unknown as StanceRow[];

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

      {/* Full manifesto. When we have an enhanced (web-sourced) manifesto we
          show it as primary because the topic + stance classification on this
          page is derived from it — readers need to see the same text the
          source_quote excerpts came from. The original vote.je listing stays
          available in a collapsed block underneath. */}
      {(c.enhanced_manifesto_text || c.manifesto_text) && (
        <section className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl p-6 mb-6">
          <h2 className="text-xl font-bold mb-3 text-gray-900 dark:text-gray-100">
            Full manifesto
          </h2>
          {hasEnhanced && c.enhanced_manifesto_source_url ? (
            <>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
                Extended platform sourced from{" "}
                <a
                  href={c.enhanced_manifesto_source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline hover:text-red-700"
                >
                  {enhancedSourceLabel}
                </a>
                {c.enhanced_manifesto_fetched_at && (
                  <>
                    {" "}
                    on{" "}
                    {new Date(
                      c.enhanced_manifesto_fetched_at,
                    ).toLocaleDateString("en-GB", {
                      day: "numeric",
                      month: "long",
                      year: "numeric",
                    })}
                  </>
                )}
                . The topic and stance analysis above is derived from this text.
              </p>
              <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap text-gray-700 dark:text-gray-300">
                {c.enhanced_manifesto_text}
              </div>
              {c.manifesto_text && (
                <details className="mt-6 border-t border-gray-100 dark:border-zinc-800 pt-4">
                  <summary className="text-sm text-gray-500 dark:text-gray-400 cursor-pointer hover:text-red-700">
                    Show original vote.je listing ({c.manifesto_word_count ?? 0}{" "}
                    words)
                  </summary>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-3 mb-3">
                    Scraped from{" "}
                    <a
                      href={c.profile_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline hover:text-red-700"
                    >
                      vote.je
                    </a>{" "}
                    on{" "}
                    {new Date(c.scraped_at).toLocaleDateString("en-GB", {
                      day: "numeric",
                      month: "long",
                      year: "numeric",
                    })}
                    .
                  </p>
                  <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap text-gray-600 dark:text-gray-400">
                    {c.manifesto_text}
                  </div>
                </details>
              )}
            </>
          ) : (
            <>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
                Scraped from{" "}
                <a
                  href={c.profile_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline hover:text-red-700"
                >
                  vote.je
                </a>{" "}
                on{" "}
                {new Date(c.scraped_at).toLocaleDateString("en-GB", {
                  day: "numeric",
                  month: "long",
                  year: "numeric",
                })}
                .
              </p>
              <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap text-gray-700 dark:text-gray-300">
                {c.manifesto_text}
              </div>
            </>
          )}
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
