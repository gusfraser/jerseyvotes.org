import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy and data handling — Jersey Votes",
  description:
    "What personal data jerseyvotes.org processes about candidates, on what legal basis, and what rights candidates have under the Data Protection (Jersey) Law 2018.",
};

const LAST_UPDATED = "21 May 2026";

export default function PrivacyPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <Link
        href="/"
        className="inline-flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 hover:text-red-700 mb-6"
      >
        &larr; Home
      </Link>

      <header className="mb-12">
        <h1 className="text-4xl sm:text-5xl font-bold text-gray-900 dark:text-gray-100 tracking-tight mb-4">
          Privacy and data handling
        </h1>
        <p className="text-lg text-gray-600 dark:text-gray-400 leading-relaxed">
          jerseyvotes.org is a free, non-partisan civic site that helps Jersey
          voters compare candidates standing in the 2026 election. This page
          explains what personal data the site processes about candidates, on
          what legal basis, and what rights candidates and visitors have
          under the Data Protection (Jersey) Law 2018.
        </p>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-4">
          Last updated: {LAST_UPDATED}
        </p>
      </header>

      <Section title="Who runs the site">
        <Prose>
          <p>
            The site is operated by Gus Fraser as an independent personal
            project. There are no funders, sponsors, or political
            affiliations. Contact:{" "}
            <ExternalLink href="mailto:gus@helix.je">gus@helix.je</ExternalLink>
            .
          </p>
        </Prose>
      </Section>

      <Section title="What data we process">
        <Prose>
          <p>For each candidate standing in the 2026 Jersey election:</p>
        </Prose>
        <ul className="space-y-2 mt-3 mb-4 text-sm text-gray-700 dark:text-gray-300 list-disc pl-5">
          <li>
            Name, role (Deputy / Connétable / Senator), parish or
            constituency, party affiliation (where stated)
          </li>
          <li>Photograph and contact details as published on vote.je</li>
          <li>
            The candidate&rsquo;s manifesto text as published on vote.je, plus
            any fuller manifesto the candidate has published publicly
            elsewhere (personal campaign site, party page, posted PDF)
          </li>
          <li>
            LLM-derived topic coverage and policy-position stances extracted
            from the published manifesto text, with verbatim source quotes
            from the candidate&rsquo;s own published material
          </li>
        </ul>
        <Prose>
          <p>
            We do not process media reports about candidates, private
            communications, or any material the candidate has not themselves
            published publicly.
          </p>
          <p>
            For sitting States Members, we also process publicly available
            voting records from{" "}
            <ExternalLink href="https://statesassembly.je">
              statesassembly.je
            </ExternalLink>
            .
          </p>
        </Prose>
      </Section>

      <Section title="Where the data comes from">
        <ul className="space-y-2 text-sm text-gray-700 dark:text-gray-300 list-disc pl-5 mb-4">
          <li>
            <ExternalLink href="https://www.vote.je/candidates">
              vote.je
            </ExternalLink>{" "}
            (the official States Greffe candidates index)
          </li>
          <li>
            Candidates&rsquo; own publicly-published manifestos (party pages,
            personal campaign sites, posted PDFs, public social media posts)
          </li>
          <li>
            <ExternalLink href="https://statesassembly.je">
              statesassembly.je
            </ExternalLink>{" "}
            (for the voting records of sitting States Members)
          </li>
        </ul>
        <Prose>
          <p>
            The site processes only material that has already been published
            by the candidate themselves or by an official public body. The
            site enforces this as a database-level invariant: any manifesto
            text we analyse must be traceable to a public URL, and the link
            is shown on the candidate&rsquo;s profile so voters can verify
            against the live source.
          </p>
        </Prose>
      </Section>

      <Section title="Lawful basis for processing">
        <Prose>
          <p>
            The site does not rely on consent. The lawful bases for
            processing are:
          </p>
        </Prose>
        <ul className="space-y-3 mt-3 text-sm text-gray-700 dark:text-gray-300 list-disc pl-5">
          <li>
            <strong>Article 6(1)(f) (legitimate interests)</strong> for
            ordinary personal data. Providing voters with structured access
            to candidates&rsquo; published positions ahead of an election is
            a substantial public interest. The balance-of-interests test
            favours processing because the underlying data is already
            manifestly public by the candidates&rsquo; own choice and the
            candidates are voluntarily seeking elected office.
          </li>
          <li>
            <strong>
              Article 9(2)(e) (special category data manifestly made public by
              the data subject)
            </strong>{" "}
            for political opinions. Candidates publish their political
            positions themselves on vote.je for the express purpose of
            informing voters, which is the textbook case for this exemption.
          </li>
          <li>
            <strong>
              Article 85 (processing for journalistic, academic, artistic and
              literary expression)
            </strong>{" "}
            provides additional cover for civic-comparison work of this
            kind, in line with how voter guides, polling-organisation
            summaries, and election journalism are routinely treated.
          </li>
        </ul>
      </Section>

      <Section title="How AI is used (and what it doesn't do)">
        <Prose>
          <p>
            The site uses a large language model (currently Claude Opus 4.7,
            made by Anthropic) to extract topic coverage and policy-position
            stances from each candidate&rsquo;s published manifesto text.
            Two design choices are central to how this works:
          </p>
        </Prose>
        <ol className="space-y-3 mt-3 text-sm text-gray-700 dark:text-gray-300 list-decimal pl-5">
          <li>
            <strong>Verbatim-quote anchoring.</strong> Every claimed topic
            and every claimed policy stance is tied to a verbatim quote from
            the candidate&rsquo;s own published manifesto. The system does
            not generate novel inferences about candidates; it surfaces
            statements candidates have made themselves and labels which
            canonical question those statements relate to. If the LLM
            produces a &ldquo;source quote&rdquo; that doesn&rsquo;t appear
            verbatim in the manifesto, the quote is dropped and the stance
            is demoted to &ldquo;not addressed&rdquo;.
          </li>
          <li>
            <strong>Source linking.</strong> Every position on a
            candidate&rsquo;s profile links back to the original document
            the candidate published it in. Voters can verify the analysis
            against the live source.
          </li>
        </ol>
        <Prose className="mt-4">
          <p>
            The full methodology — including the prompt templates, the
            canonical question set, and the scoring formula — is documented
            at{" "}
            <Link
              href="/candidates/methodology"
              className="text-red-700 hover:underline"
            >
              /candidates/methodology
            </Link>
            . The pipeline and web code are open-source under the MIT licence
            at{" "}
            <ExternalLink href="https://github.com/gusfraser/jerseyvotes.org">
              github.com/gusfraser/jerseyvotes.org
            </ExternalLink>
            .
          </p>
        </Prose>
      </Section>

      <Section title="Your rights">
        <Prose>
          <p>
            Under the Data Protection (Jersey) Law 2018, you have the
            following rights as a data subject. For this site specifically:
          </p>
        </Prose>
        <ul className="space-y-3 mt-3 text-sm text-gray-700 dark:text-gray-300 list-disc pl-5">
          <li>
            <strong>Right of access.</strong> See exactly what the site says
            about you via the private review link sent to you by email. If
            you&rsquo;ve lost the link, request a new one via{" "}
            <ExternalLink href="mailto:gus@helix.je">
              gus@helix.je
            </ExternalLink>
            .
          </li>
          <li>
            <strong>Right to rectification.</strong> Flag any incorrect topic,
            stance, or quote via the review link or by email. Valid
            corrections are acted on within 24 hours.
          </li>
          <li>
            <strong>Right to object and to opt out.</strong> Opt out of
            analysis at any time from the private review link, or by email.
            Opting out removes the topic and policy-position analysis from
            your public profile and excludes you from the matching quiz
            immediately. Your name, role, parish, and party remain in the
            candidate index — those are public States Greffe facts about who
            is standing in the election — with a link to your vote.je
            profile instead of any extracted content.
          </li>
          <li>
            <strong>Right to human review and to contest a decision.</strong>{" "}
            All LLM processing is supervised by Gus Fraser. You have the
            right to request a human review of any extraction, to express
            your point of view, and to contest the result. Email{" "}
            <ExternalLink href="mailto:gus@helix.je">
              gus@helix.je
            </ExternalLink>
            .
          </li>
          <li>
            <strong>Right to erasure.</strong> If you wish to be removed from
            the site entirely (name as well as analysis), email{" "}
            <ExternalLink href="mailto:gus@helix.je">
              gus@helix.je
            </ExternalLink>
            . This will be actioned within 24 hours unless there is an
            overriding public interest in retention.
          </li>
          <li>
            <strong>Right to complain.</strong> You can complain to the
            Jersey Office of the Information Commissioner at{" "}
            <ExternalLink href="https://jerseyoic.org">
              jerseyoic.org
            </ExternalLink>
            .
          </li>
        </ul>
      </Section>

      <Section title="Automated decision-making">
        <Prose>
          <p>
            The LLM extraction described above is automated processing. The
            site provides the safeguards required under Article 22 of the
            DPL: human review on request, the ability to express your point
            of view, the ability to contest the result, and meaningful
            information about the logic involved (the{" "}
            <Link
              href="/candidates/methodology"
              className="text-red-700 hover:underline"
            >
              methodology page
            </Link>{" "}
            documents prompts, the scoring formula, and the open-source
            code).
          </p>
        </Prose>
      </Section>

      <Section title="Recipients and international transfers">
        <ul className="space-y-2 text-sm text-gray-700 dark:text-gray-300 list-disc pl-5 mb-4">
          <li>
            Manifesto text is sent to{" "}
            <ExternalLink href="https://www.anthropic.com">
              Anthropic
            </ExternalLink>
            &rsquo;s API in the United States for LLM processing. Anthropic
            processes the data as a processor on the site&rsquo;s behalf,
            subject to its own commitments on privacy and security.
          </li>
          <li>
            The site&rsquo;s database is hosted by{" "}
            <ExternalLink href="https://neon.tech">Neon</ExternalLink>. All
            data stored is publicly-sourced manifesto material plus
            operational metadata; no private candidate communications are
            stored.
          </li>
          <li>
            The site is hosted on{" "}
            <ExternalLink href="https://render.com">Render</ExternalLink>{" "}
            with{" "}
            <ExternalLink href="https://www.cloudflare.com">
              Cloudflare
            </ExternalLink>{" "}
            in front of it.
          </li>
        </ul>
        <Prose>
          <p>
            International transfers rely on the standard contractual terms
            of those providers, in line with DPJL transfer requirements.
          </p>
        </Prose>
      </Section>

      <Section title="Retention">
        <Prose>
          <p>
            Candidate analysis is retained for the duration of the 2026
            election cycle and thereafter as part of the site&rsquo;s
            historical record (so that the methodology and its application
            to a specific election can be audited in the future). Opt-out
            is immediate. Full erasure on request, as above.
          </p>
        </Prose>
      </Section>

      <Section title="Voter data">
        <Prose>
          <p>
            The site does not require visitors to sign up, log in, or
            provide personal data. No cookies are set, and no tracking
            scripts are loaded. Quiz answers are stored only in the
            visitor&rsquo;s browser (localStorage) and are not transmitted
            to the server. Aggregate request metadata visible to the
            site&rsquo;s hosting provider (page viewed, referrer,
            IP-derived geography) is not retained beyond their standard
            operational logs.
          </p>
        </Prose>
      </Section>

      <Section title="Updates">
        <Prose>
          <p>
            This notice was last updated on {LAST_UPDATED}. Material
            changes will be summarised in the methodology page changelog
            at{" "}
            <Link
              href="/candidates/methodology"
              className="text-red-700 hover:underline"
            >
              /candidates/methodology
            </Link>
            .
          </p>
        </Prose>
      </Section>

      <div className="mt-16 pt-8 border-t border-gray-200 dark:border-zinc-800">
        <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100 mb-2">
          Questions, corrections, opt-outs, or any data protection enquiry
        </h2>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
          Email Gus directly.
        </p>
        <a
          href={`mailto:gus@helix.je?subject=${encodeURIComponent("Jersey Votes — privacy enquiry")}`}
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
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M3 8l9 6 9-6M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
            />
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
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-14 pt-8 border-t border-gray-200 dark:border-zinc-800">
      <h2 className="text-2xl font-bold text-gray-900 dark:text-gray-100 tracking-tight mb-5">
        {title}
      </h2>
      {children}
    </section>
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
    <div
      className={`space-y-3 text-gray-700 dark:text-gray-300 leading-relaxed ${className}`}
    >
      {children}
    </div>
  );
}

function ExternalLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  const isExternal = href.startsWith("http");
  return (
    <a
      href={href}
      {...(isExternal
        ? { target: "_blank", rel: "noopener noreferrer" }
        : {})}
      className="text-red-700 hover:underline"
    >
      {children}
    </a>
  );
}
