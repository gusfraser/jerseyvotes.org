import type { Metadata } from "next";
import Link from "next/link";
import { sql, TOPICS } from "@/lib/db";
import { TrackView } from "@/lib/track-view";

export const metadata: Metadata = {
  title: "How we score candidates — Methodology",
  description:
    "The full methodology behind the Jersey Votes candidate matcher. Data sources, scoring formula, LLM prompts, and limitations — published openly so voters and journalists can audit it.",
};

export default async function MethodologyPage() {
  const [statsRow, questionRowsAny] = await Promise.all([
    sql`
      SELECT
        (SELECT COUNT(*) FROM candidates WHERE election_year = 2026) AS total,
        (SELECT COUNT(*) FROM candidates WHERE election_year = 2026 AND classified_at IS NOT NULL) AS classified,
        (SELECT COUNT(*) FROM candidates WHERE election_year = 2026 AND incumbent_member_id IS NOT NULL) AS incumbents,
        (SELECT COUNT(*) FROM candidates WHERE election_year = 2026 AND scrape_status = 'low_content') AS low_content,
        (SELECT COUNT(*) FROM canonical_questions WHERE election_year = 2026) AS questions,
        (SELECT MAX(scraped_at) FROM candidates WHERE election_year = 2026) AS last_scrape
    `,
    sql`
      SELECT topic, statement
      FROM canonical_questions
      WHERE election_year = 2026
      ORDER BY topic, sort_order
    `,
  ]);
  const stats = statsRow[0] as Record<string, unknown>;
  const questionRows = questionRowsAny as unknown as {
    topic: string;
    statement: string;
  }[];

  // Group up to 2 example statements per topic for the taxonomy section
  const examplesByTopic = new Map<string, string[]>();
  for (const r of questionRows) {
    const arr = examplesByTopic.get(r.topic) ?? [];
    if (arr.length < 2) arr.push(r.statement);
    examplesByTopic.set(r.topic, arr);
  }

  const lastRefreshed = stats.last_scrape
    ? new Date(String(stats.last_scrape)).toLocaleDateString("en-GB", {
        day: "numeric",
        month: "long",
        year: "numeric",
      })
    : null;

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <TrackView event="candidate_methodology_viewed" />
      <Link
        href="/candidates"
        className="inline-flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 hover:text-red-700 mb-6"
      >
        &larr; All candidates
      </Link>

      {/* Hero */}
      <header className="mb-12">
        <h1 className="text-4xl sm:text-5xl font-bold text-gray-900 dark:text-gray-100 tracking-tight mb-4">
          How we score candidates
        </h1>
        <p className="text-lg text-gray-600 dark:text-gray-400 leading-relaxed">
          This page documents exactly how the Jersey Votes candidate matcher
          works — the data sources, scoring formula, LLM prompts, limitations,
          and candidate-correction process. We publish this so anyone can audit
          our methodology before relying on the results.
        </p>
      </header>

      {/* Quick numbers — stat grid */}
      <Section title="Quick numbers" subtitle={lastRefreshed ? `Last refreshed ${lastRefreshed}` : undefined}>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          <Stat label="Candidates scraped from vote.je" value={String(stats.total ?? 0)} />
          <Stat label="Classified into the policy taxonomy" value={String(stats.classified ?? 0)} />
          <Stat label="Linked to a sitting States Member" value={String(stats.incumbents ?? 0)} />
          <Stat
            label={'Flagged as "short manifesto" (<150 words)'}
            value={String(stats.low_content ?? 0)}
          />
          <Stat label="Canonical policy statements" value={String(stats.questions ?? 0)} />
          <Stat label="Topics in the taxonomy" value="16" />
        </div>
      </Section>

      {/* How Jersey voting works */}
      <Section title="How Jersey voting works">
        <Prose>
          <p>
            On <strong>Sunday 7 June 2026</strong> every voter elects three
            different types of States Member:
          </p>
        </Prose>
        <ul className="space-y-2 mt-4 text-sm text-gray-700 dark:text-gray-300">
          <li className="flex items-baseline gap-2">
            <span className="w-1.5 h-1.5 bg-red-700 rounded-full flex-shrink-0" />
            <span>
              <strong>Senators</strong> — up to <strong>9</strong> candidates,
              elected to represent the whole Island. Every voter sees the same
              17-candidate Senator list.
            </span>
          </li>
          <li className="flex items-baseline gap-2">
            <span className="w-1.5 h-1.5 bg-red-700 rounded-full flex-shrink-0" />
            <span>
              <strong>Connétable</strong> (Constable) — exactly{" "}
              <strong>1</strong> per parish. Voters pick from candidates
              standing in their parish only.
            </span>
          </li>
          <li className="flex items-baseline gap-2">
            <span className="w-1.5 h-1.5 bg-red-700 rounded-full flex-shrink-0" />
            <span>
              <strong>Deputies</strong> — <strong>2 to 4</strong> per
              constituency, depending on which of the nine Deputy
              constituencies you live in. Some constituencies match a single
              parish; some split a parish (3 districts inside St Helier); some
              combine parishes (e.g. &ldquo;St Mary, St Ouen and St Peter&rdquo;).
            </span>
          </li>
        </ul>
        <Prose className="mt-4">
          <p>
            Source:{" "}
            <ExternalLink href="https://www.vote.je/">vote.je</ExternalLink>
            , maintained by the States Greffe. Not sure which Deputy
            constituency covers your address? Use the official{" "}
            <ExternalLink href="https://www.vote.je/constituency-finder/">
              constituency finder
            </ExternalLink>{" "}
            on vote.je to look it up by postcode.
          </p>
          <p>
            When you pick your parish in the quiz or on the candidates index,
            we show you everyone you can actually vote for: the Connétable for
            that parish, the Deputies standing in whichever constituency
            covers it, and all Senators.
          </p>
        </Prose>
      </Section>

      {/* Data sources */}
      <Section title="Data sources">
        <Prose>
          <p>
            Candidate profiles are scraped from the official{" "}
            <ExternalLink href="https://www.vote.je/candidates">
              vote.je candidates index
            </ExternalLink>{" "}
            maintained by the States Greffe. For each candidate we collect:
            name, parish/district, role (Deputy / Connétable / Senator), party
            (if any), photo, contact details, and the full manifesto text.
            Manifestos are extracted from the candidate&rsquo;s profile-page
            content block (between the convictions section and the proposers
            list).
          </p>
          <p>
            Sitting members have separate voting records from{" "}
            <ExternalLink href="https://statesassembly.je">statesassembly.je</ExternalLink>{" "}
            going back to 2004. We link candidates to those records by
            normalised name matching where it&rsquo;s safe to do so; otherwise
            the candidate is treated as a new entrant.
          </p>
        </Prose>
      </Section>

      {/* Taxonomy */}
      <Section title="The 16-topic taxonomy">
        <Prose>
          <p>
            Every manifesto is classified against the same 16-category
            taxonomy we use across the rest of this site for proposition
            classification — that keeps candidate analysis directly
            comparable to voting-record analysis. Each topic below is
            illustrated with one or two example statements from the
            quiz&rsquo;s canonical question set, so the abstract category
            name has something concrete attached.
          </p>
        </Prose>
        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-6">
          {TOPICS.map((t) => {
            const examples = examplesByTopic.get(t) ?? [];
            return (
              <li
                key={t}
                className="bg-gray-50 dark:bg-zinc-950 border border-gray-200 dark:border-zinc-800 rounded-lg p-4"
              >
                <p className="font-semibold text-gray-900 dark:text-gray-100 mb-2 text-sm">
                  {t}
                </p>
                {examples.length === 0 ? (
                  <p className="text-xs italic text-gray-400 dark:text-gray-500">
                    No canonical questions defined for this topic.
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {examples.map((ex, i) => (
                      <li
                        key={i}
                        className="flex items-baseline gap-2 text-xs text-gray-600 dark:text-gray-400"
                      >
                        <span
                          aria-hidden="true"
                          className="text-red-700 flex-shrink-0"
                        >
                          ›
                        </span>
                        <span className="leading-snug">
                          &ldquo;{ex}&rdquo;
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-4">
          These statements are taken verbatim from{" "}
          <Code>pipeline/canonical_questions.yaml</Code> in the repo — that
          file is the source of truth and is versioned with the rest of the
          site.
        </p>
      </Section>

      {/* How positions are extracted */}
      <Section title="How positions are extracted">
        <Prose>
          <p>
            For each candidate we run two LLM passes (Claude Sonnet 4.5) over
            the manifesto. We use Sonnet rather than the cheaper Haiku here
            because extracting stances from free-form prose — especially
            implicit, hedged, or conditional positions — needs more reading
            comprehension than a topic-tagging task does. The rest of this
            site&rsquo;s pipeline (the proposition classifier) still uses
            Haiku, where it&rsquo;s well-calibrated.
          </p>
        </Prose>

        <ol className="mt-5 space-y-4">
          <NumberedItem n={1} title="Topic extraction">
            The model identifies which of the 16 categories the manifesto
            substantively addresses, estimates a <em>salience</em> score (its
            share of the manifesto, 0–1, summed ≤ 1), writes a one-sentence
            summary of the candidate&rsquo;s position, and returns a verbatim
            source quote.
          </NumberedItem>
          <NumberedItem n={2} title="Stance extraction">
            Against a fixed list of {String(stats.questions ?? 40)} canonical
            policy statements, the model marks the candidate as{" "}
            <Code>agree</Code>, <Code>disagree</Code>, <Code>neutral</Code>, or{" "}
            <Code>not_addressed</Code>, with a verbatim source quote when the
            stance is anything other than not_addressed.
          </NumberedItem>
        </ol>

        <Callout title="Verbatim-quote check (the trust anchor)">
          Every claimed source quote is string-matched against the
          candidate&rsquo;s manifesto after whitespace and smart-quote
          normalisation. If the quote doesn&rsquo;t appear verbatim, we treat
          it as hallucinated, drop the quote, and demote the stance to{" "}
          <Code>not_addressed</Code>. This is the primary protection against
          the model inventing positions.
        </Callout>

        <Prose className="mt-5">
          <p>
            The full prompt templates live in{" "}
            <Code>pipeline/classify_candidates.py</Code>; the canonical
            question list is in <Code>pipeline/canonical_questions.yaml</Code>.
            Both are versioned alongside the site in the public repo at{" "}
            <ExternalLink href="https://github.com/gusfraser/jerseyvotes.org">
              github.com/gusfraser/jerseyvotes.org
            </ExternalLink>
            .
          </p>
        </Prose>
      </Section>

      {/* Scoring formula */}
      <Section title="The scoring formula">
        <SubSection title="Step 1 — your priorities">
          <Prose>
            <p>
              You rank up to 5 topics from the 16 in order of personal
              importance. Each rank gets a weight: <strong>1st = 5</strong>,
              2nd = 4, 3rd = 3, 4th = 2, 5th = 1. Topics you didn&rsquo;t rank
              get weight <strong>0</strong>.
            </p>
          </Prose>
        </SubSection>

        <SubSection title="Step 2 — topic priority overlap (T)">
          <Prose>
            <p>
              How much of each candidate&rsquo;s manifesto goes to topics you
              care about, weighted by your ranking:
            </p>
          </Prose>
          <Formula
            numerator="Σ over topics ( user_weight[topic] × candidate_salience[c, topic] )"
            denominator="Σ over topics ( user_weight[topic] )"
            label="T(c)"
          />
          <Prose>
            <p>
              T is in <Code>[0, 1]</Code>. Higher = the manifesto devotes
              attention to what matters to you.
            </p>
          </Prose>
        </SubSection>

        <SubSection title="Step 3 — stance alignment (S)">
          <Prose>
            <p>
              For each canonical question where you answered
              agree/disagree/neutral (not &ldquo;skip&rdquo;) and the candidate
              took a definite position (not &ldquo;not addressed&rdquo;):
            </p>
          </Prose>
          <ul className="my-4 space-y-2 text-sm text-gray-700 dark:text-gray-300">
            <MatchRule
              kind="full"
              label="match = 1"
              detail="Both agree (or both disagree, or both neutral)"
            />
            <MatchRule
              kind="none"
              label="match = 0"
              detail="One agrees, the other disagrees"
            />
            <MatchRule
              kind="half"
              label="match = 0.5"
              detail="One is neutral, the other has a direction — partial credit"
            />
          </ul>
          <Prose>
            <p>
              Each match is weighted by the priority rank of its topic (with
              weight 1 for off-priority topics, so agreement on a non-priority
              topic still counts a bit):
            </p>
          </Prose>
          <Formula
            numerator="Σ over matched_q ( topic_weight[topic(q)] × match[q] )"
            denominator="Σ over matched_q ( topic_weight[topic(q)] )"
            label="S(c)"
          />
        </SubSection>

        <SubSection title="Step 4 — coverage (C)">
          <Prose>
            <p>
              How confident is this match? We compute the share of canonical
              questions on your priority topics that the candidate took any
              position on:
            </p>
          </Prose>
          <Formula
            numerator="# priority questions where stance ≠ not_addressed"
            denominator="total # priority questions"
            label="C(c)"
          />
          <Prose>
            <p>
              C is shown <strong>separately</strong>, not blended into the main
              match score. If C is below <Code>0.4</Code> we explicitly flag
              the result as &ldquo;low coverage&rdquo; — the candidate
              didn&rsquo;t address most of what matters to you, so the match
              score is based on limited information rather than disagreement.
            </p>
          </Prose>
        </SubSection>

        <SubSection title="Step 5 — final match score">
          <FinalFormula expression="Match(c) = 0.4 × T(c) + 0.6 × S(c)" />
          <Prose className="mt-4">
            <p>
              Stance carries more weight than topic salience because{" "}
              <em>direction matters more than attention</em>: a candidate who
              talks a lot about housing but disagrees with you on housing
              should not score higher than one who agrees with you but writes
              briefly. The 60/40 blend is deliberately not exposed as a knob
              to users — exposing too many weights would invite cherry-picking.
              The numbers live in{" "}
              <Code>web/src/app/api/candidates/quiz/route.ts</Code>.
            </p>
            <p>
              Scores are rounded to whole percents in the UI; ties break by
              stance-only alignment, then by alphabetical name. We deliberately
              don&rsquo;t cling to 0.1% differences — they aren&rsquo;t
              meaningful here.
            </p>
          </Prose>
        </SubSection>
      </Section>

      {/* Receipts */}
      <Section title="Showing the receipts">
        <Prose>
          <p>
            Every position we attribute to a candidate links back to a
            verbatim quote from their own manifesto. Visit any candidate page
            and you can inspect, topic-by-topic, the actual sentence that
            justified each extracted stance. If we don&rsquo;t have a
            verifiable quote, we don&rsquo;t claim a position.
          </p>
          <p>
            Results pages show the three sub-scores (<strong>T</strong>,{" "}
            <strong>S</strong>, <strong>C</strong>) and the matched/answered
            count alongside the headline percentage — so you can see{" "}
            <em>why</em> a candidate scored where they did, not just the
            number.
          </p>
        </Prose>
      </Section>

      {/* Incumbent overlay */}
      <Section title="Incumbent overlay">
        <Prose>
          <p>
            Where a candidate is also a sitting member, their candidate page
            links to their full Assembly voting record. The voting-record
            match (from our{" "}
            <Link
              href="/quiz"
              className="text-red-700 hover:underline"
            >
              voting-record quiz
            </Link>
            ) and the manifesto-based match are shown side-by-side, not
            blended. The gap between them — what a member <em>did</em> vs what
            they now <em>say</em> — is often more informative than either
            alone.
          </p>
        </Prose>
      </Section>

      {/* Correction process */}
      <Section title="Candidate correction process">
        <Callout title="We are reaching out to candidates now">
          The candidate classifications are live on the site, and we are
          contacting each candidate with a private preview so they can flag
          any errors before polling day. Until the candidate has responded,
          treat the published figures as our best automated reading of the
          manifesto, not the candidate&rsquo;s own confirmed positions.
        </Callout>
        <Prose className="mt-5">
          <p>
            Each candidate receives a unique token-gated preview link by email.
            From that preview they can email{" "}
            <ExternalLink href="mailto:gus@helix.je">gus@helix.je</ExternalLink>{" "}
            with the profile link and token pre-filled — no form to sign up
            for, no account to create. Every public candidate page also has a
            &ldquo;Report it&rdquo; link that opens the same email flow with
            the candidate&rsquo;s name pre-filled. We aim to process valid
            corrections within 24 hours and timestamp the candidate&rsquo;s
            page accordingly.
          </p>
          <p>
            When a correction overrides an LLM-extracted stance, the corrected
            value is shown and the original is kept in the database for
            transparency. The methodology cannot be silently changed
            retroactively.
          </p>
        </Prose>
      </Section>

      {/* Limitations */}
      <Section title="Known limitations">
        <ul className="space-y-4 mt-2">
          <Limitation title="Short manifestos">
            Some candidates publish under 150 words, mostly biographical. We
            flag these as &ldquo;short manifesto&rdquo; — they will tend to
            show low coverage (C) and should be evaluated cautiously regardless
            of headline %.
          </Limitation>
          <Limitation title="Single source">
            We only use the vote.je manifesto text. Hustings, social media,
            blogs, and prior public statements are not included. A
            candidate&rsquo;s actual views may be richer than their manifesto.
          </Limitation>
          <Limitation title="LLM error">
            Even with the verbatim-quote guard, the model can mis-classify
            nuance. Always check the receipts on the candidate page before
            deciding how to vote.
          </Limitation>
          <Limitation title="Canonical questions are subjective">
            The list of policy statements is curated. We try to frame them
            neutrally and cover both incumbent priorities and opposition
            framings, but no list is fully neutral.
          </Limitation>
          <Limitation title="Not financial / legal advice">
            This is one input among many for an informed vote.
          </Limitation>
        </ul>
      </Section>

      {/* Source code */}
      <Section title="Source code and licence">
        <Prose>
          <p>
            The pipeline (Python) and the web app (TypeScript / Next.js) are
            open source, MIT licensed, and live at{" "}
            <ExternalLink href="https://github.com/gusfraser/jerseyvotes.org">
              github.com/gusfraser/jerseyvotes.org
            </ExternalLink>
            . Pull requests and issues — including disputes about specific
            candidate classifications — are welcome.
          </p>
        </Prose>
      </Section>

      <div className="mt-16 pt-8 border-t border-gray-200 dark:border-zinc-800">
        <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100 mb-2">
          Got a question, correction, or complaint?
        </h2>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
          Email Gus directly. Candidates flagging an error about their own
          profile, voters spotting a misclassification, or journalists with a
          methodology question — all welcome to the same inbox.
        </p>
        <a
          href={`mailto:gus@helix.je?subject=${encodeURIComponent("Jersey Votes — candidate matcher")}`}
          className="inline-flex items-center gap-2 px-4 py-2 bg-red-700 text-white rounded-md hover:bg-red-800 font-medium text-sm"
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
          gus@helix.je
        </a>
      </div>
    </div>
  );
}

/* -------------------- presentational helpers -------------------- */

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-14 pt-8 border-t border-gray-200 dark:border-zinc-800">
      <div className="flex items-baseline justify-between gap-4 mb-5 flex-wrap">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-gray-100 tracking-tight">
          {title}
        </h2>
        {subtitle && (
          <span className="text-xs text-gray-500 dark:text-gray-400">{subtitle}</span>
        )}
      </div>
      {children}
    </section>
  );
}

function SubSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-6 first:mt-0">
      <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100 mb-2">
        {title}
      </h3>
      {children}
    </div>
  );
}

function Prose({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`space-y-3 text-gray-700 dark:text-gray-300 leading-relaxed ${className}`}>
      {children}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-gray-50 dark:bg-zinc-950 border border-gray-200 dark:border-zinc-800 rounded-lg p-4">
      <p className="text-3xl font-bold text-red-700 tabular-nums">{value}</p>
      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 leading-snug">
        {label}
      </p>
    </div>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="text-[0.85em] font-mono bg-gray-100 dark:bg-zinc-800 text-gray-800 dark:text-gray-200 px-1.5 py-0.5 rounded border border-gray-200 dark:border-zinc-700">
      {children}
    </code>
  );
}

function ExternalLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-red-700 hover:underline"
    >
      {children}
    </a>
  );
}

function NumberedItem({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="flex gap-4">
      <span
        aria-hidden="true"
        className="flex-shrink-0 w-7 h-7 rounded-full bg-red-700 text-white text-sm font-bold flex items-center justify-center"
      >
        {n}
      </span>
      <div className="flex-1 pt-0.5">
        <p className="font-semibold text-gray-900 dark:text-gray-100 mb-1">
          {title}
        </p>
        <p className="text-gray-700 dark:text-gray-300 leading-relaxed text-sm sm:text-base">
          {children}
        </p>
      </div>
    </li>
  );
}

function Callout({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-5 rounded-lg border-l-4 border-red-700 bg-red-50 dark:bg-red-950/30 p-4">
      <p className="font-semibold text-red-900 dark:text-red-200 mb-1">
        {title}
      </p>
      <p className="text-sm text-red-900/90 dark:text-red-200/90 leading-relaxed">
        {children}
      </p>
    </div>
  );
}

function Formula({
  numerator,
  denominator,
  label,
}: {
  numerator: string;
  denominator: string;
  label: string;
}) {
  return (
    <div className="my-4 bg-gray-50 dark:bg-zinc-950 border border-gray-200 dark:border-zinc-800 rounded-lg p-5 overflow-x-auto">
      <div className="flex items-center gap-4 font-mono text-sm">
        <span className="text-gray-900 dark:text-gray-100 font-semibold whitespace-nowrap">
          {label} =
        </span>
        <div className="flex flex-col items-center min-w-0">
          <span className="px-3 pb-1 text-gray-800 dark:text-gray-200 whitespace-nowrap">
            {numerator}
          </span>
          <span className="block w-full h-px bg-gray-400 dark:bg-zinc-600" />
          <span className="px-3 pt-1 text-gray-800 dark:text-gray-200 whitespace-nowrap">
            {denominator}
          </span>
        </div>
      </div>
    </div>
  );
}

function FinalFormula({ expression }: { expression: string }) {
  return (
    <div className="my-4 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 rounded-lg p-5 text-center">
      <code className="font-mono text-lg text-red-900 dark:text-red-200 font-semibold">
        {expression}
      </code>
    </div>
  );
}

function MatchRule({
  kind,
  label,
  detail,
}: {
  kind: "full" | "half" | "none";
  label: string;
  detail: string;
}) {
  const colour =
    kind === "full"
      ? "bg-green-100 dark:bg-green-900/40 text-green-800 dark:text-green-300 border-green-300 dark:border-green-800"
      : kind === "half"
      ? "bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 border-amber-300 dark:border-amber-800"
      : "bg-red-100 dark:bg-red-900/40 text-red-800 dark:text-red-300 border-red-300 dark:border-red-800";
  return (
    <li className="flex items-baseline gap-3">
      <span
        className={`text-xs font-mono font-semibold px-2 py-0.5 rounded border whitespace-nowrap ${colour}`}
      >
        {label}
      </span>
      <span>{detail}</span>
    </li>
  );
}

function Limitation({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-lg p-4">
      <p className="font-semibold text-gray-900 dark:text-gray-100 mb-1">
        {title}
      </p>
      <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
        {children}
      </p>
    </li>
  );
}
