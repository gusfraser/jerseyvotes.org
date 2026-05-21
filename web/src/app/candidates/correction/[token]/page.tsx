import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { sql } from "@/lib/db";

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
  opted_out_at: string | null;
};

// Server Action: candidate self-removal. Submitted from the opt-out form at
// the bottom of the review page. Confirmation text guard prevents misclicks
// and stops shared-link / prefetch accidental triggers.
async function optOutAction(formData: FormData) {
  "use server";
  const token = String(formData.get("token") ?? "");
  const confirmation = String(formData.get("confirmation") ?? "").trim();
  if (!token) notFound();
  if (confirmation !== "OPT OUT") {
    redirect(`/candidates/correction/${token}?error=confirm`);
  }
  await sql`
    UPDATE candidates
    SET opted_out_at = NOW()
    WHERE correction_token = ${token}
      AND opted_out_at IS NULL
  `;
  // Drop opted-out candidate from public listings immediately.
  revalidatePath("/");
  revalidatePath("/candidates");
  revalidatePath("/candidates/quiz");
  revalidatePath("/sitemap.xml");
  revalidatePath(`/candidates/correction/${token}`);
}

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
  searchParams,
}: {
  params: Promise<{ token: string }>;
  searchParams: Promise<{ error?: string }>;
}) {
  const { token } = await params;
  const { error } = await searchParams;
  const rows = (await sql`
    SELECT candidate_id, vote_je_slug, full_name, role, constituency, party,
           manifesto_text, manifesto_word_count, correction_state,
           scraped_at, classified_at, opted_out_at
    FROM candidates
    WHERE correction_token = ${token}
    LIMIT 1
  `) as unknown as CandidateWithExtractions[];

  const candidate = rows[0];
  if (!candidate) notFound();

  // Post-opt-out view: clear confirmation, no manifesto/topics/stances shown.
  if (candidate.opted_out_at) {
    return <OptedOutView candidate={candidate} />;
  }

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
          Your profile is live — please review
        </p>
        <p className="text-sm text-amber-800 dark:text-amber-300">
          This is a private review link for{" "}
          <strong>{candidate.full_name}</strong>. Your public profile is
          already live at{" "}
          <a
            href={`/candidates/${candidate.vote_je_slug}`}
            target="_blank"
            rel="noopener noreferrer"
            className="underline font-medium hover:no-underline"
          >
            jerseyvotes.org/candidates/{candidate.vote_je_slug}
          </a>
          . Please check that the topics and policy positions below correctly
          reflect your manifesto. If anything is wrong, use the form at the
          bottom of this page to flag it — we&rsquo;ll review and update
          within 24 hours. This review page itself is unlisted and not
          indexed by search engines.
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
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
          If we&rsquo;ve got something wrong, email Gus directly — tell us
          specifically which topic or statement and what should change. Most
          valid corrections are processed within 24 hours.
        </p>
        {(() => {
          const subject = `Candidate correction: ${candidate.full_name}`;
          const body = [
            `Profile: https://jerseyvotes.org/candidates/${candidate.vote_je_slug}`,
            `Token: ${token}`,
            ``,
            `What's wrong, and what should it say?`,
            ``,
            `(Please be specific — e.g. "On the housing statement about binding affordable targets, my manifesto actually supports binding targets — see paragraph 3.")`,
            ``,
          ].join("\n");
          const href = `mailto:gus@helix.je?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
          return (
            <a
              href={href}
              className="inline-flex items-center gap-2 px-5 py-3 bg-red-700 text-white rounded-lg hover:bg-red-800 font-semibold text-sm"
            >
              <svg
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l9 6 9-6M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
              Email correction to gus@helix.je
            </a>
          );
        })()}
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-3">
          The email opens with the profile link and a unique token already
          filled in, so we can match your reply to this preview. Just add
          your note and send.
        </p>
      </section>

      <section className="mb-8 mt-12 pt-8 border-t border-gray-200 dark:border-zinc-800">
        <h2 className="text-xl font-bold mb-3 text-gray-900 dark:text-gray-100">
          Remove my profile
        </h2>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
          If you&rsquo;d rather not appear on jerseyvotes.org at all, you can
          remove your profile from here. This will hide your name, manifesto
          extracts, and policy positions from the candidate index, your public
          profile page, search results, the matching quiz, and the sitemap.
          The action takes effect immediately. To reverse it later, email{" "}
          <a href="mailto:gus@helix.je" className="underline hover:text-red-700">
            gus@helix.je
          </a>
          .
        </p>
        {error === "confirm" && (
          <div className="mb-4 rounded-md border border-red-300 bg-red-50 dark:bg-red-950/30 dark:border-red-900 p-3 text-sm text-red-800 dark:text-red-200">
            The confirmation text didn&rsquo;t match. Type{" "}
            <code className="font-mono">OPT OUT</code> exactly (capitals, with
            the space) to confirm removal.
          </div>
        )}
        <form action={optOutAction} className="space-y-3">
          <input type="hidden" name="token" value={token} />
          <label className="block text-sm">
            <span className="block text-gray-700 dark:text-gray-300 mb-1">
              Type <code className="font-mono font-semibold">OPT OUT</code> to
              confirm:
            </span>
            <input
              type="text"
              name="confirmation"
              required
              pattern="OPT OUT"
              autoComplete="off"
              spellCheck={false}
              className="w-full max-w-xs px-3 py-2 border border-gray-300 dark:border-zinc-700 rounded-md bg-white dark:bg-zinc-900 text-gray-900 dark:text-gray-100 font-mono focus:outline-none focus:ring-2 focus:ring-red-700"
            />
          </label>
          <button
            type="submit"
            className="inline-flex items-center gap-2 px-5 py-3 bg-red-700 text-white rounded-lg hover:bg-red-800 font-semibold text-sm"
          >
            Remove my profile from jerseyvotes.org
          </button>
        </form>
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

function OptedOutView({ candidate }: { candidate: CandidateWithExtractions }) {
  const optedOutOn = new Date(candidate.opted_out_at!).toLocaleString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <div className="bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-800 rounded-lg p-5 mb-6">
        <p className="font-semibold text-green-900 dark:text-green-200 mb-1">
          Profile removed
        </p>
        <p className="text-sm text-green-900/90 dark:text-green-200/90 leading-relaxed">
          The profile for <strong>{candidate.full_name}</strong> was removed
          from jerseyvotes.org on {optedOutOn}. Your name, manifesto extracts,
          and policy positions no longer appear in the candidate index, your
          public profile page, search results, the matching quiz, or the
          sitemap.
        </p>
      </div>
      <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100 mb-2">
        {candidate.full_name}
      </h1>
      <p className="text-gray-500 dark:text-gray-400 mb-6">
        {[candidate.role, candidate.constituency, candidate.party]
          .filter(Boolean)
          .join(" — ")}
      </p>
      <section className="mb-8">
        <h2 className="text-xl font-bold mb-3 text-gray-900 dark:text-gray-100">
          Want to reverse this?
        </h2>
        <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed mb-4">
          To re-enable your profile (either as-is or with corrections), email
          Gus directly. We&rsquo;ll restore it as soon as we&rsquo;ve had a
          chance to apply any changes you ask for.
        </p>
        <a
          href={`mailto:gus@helix.je?subject=${encodeURIComponent(
            `Re-enable my jerseyvotes.org profile: ${candidate.full_name}`,
          )}`}
          className="inline-flex items-center gap-2 px-5 py-3 bg-red-700 text-white rounded-lg hover:bg-red-800 font-semibold text-sm"
        >
          Email gus@helix.je
        </a>
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
