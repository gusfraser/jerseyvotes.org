import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "About",
  description:
    "Jersey Votes is an open-source civic transparency platform built to help Jersey residents understand how their elected representatives vote.",
};

export default function AboutPage() {
  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <h1 className="text-3xl font-bold mb-8">About Jersey Votes</h1>

      <div className="bg-white rounded-lg border border-gray-200 p-8 space-y-6 text-gray-700 leading-relaxed">
        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">
            Why this exists
          </h2>
          <p>
            Jersey has one of the lowest voter turnout rates in Europe. Many
            islanders feel disconnected from the political process, unsure which
            candidates align with their views, or simply unaware of how their
            elected representatives actually vote once in office.
          </p>
          <p className="mt-3">
            Jersey Votes was built to change that. By making 22 years of States
            Assembly voting data accessible and understandable, we aim to help
            every Jersey resident make informed decisions at the ballot box.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">
            What we do
          </h2>
          <ul className="list-disc pl-5 space-y-2">
            <li>
              <strong>Show how the Assembly votes</strong> &mdash; every
              recorded vote since 2004, broken down by member, topic, and
              outcome
            </li>
            <li>
              <strong>Help voters find aligned representatives</strong> &mdash;
              our Voter Quiz matches your views against real voting records, not
              campaign promises
            </li>
            <li>
              <strong>Reveal voting patterns</strong> &mdash; see which members
              vote together, who votes independently, and how informal blocs
              form in the Assembly
            </li>
            <li>
              <strong>Make politics accessible</strong> &mdash; plain-language
              summaries of every proposition, so you don&apos;t need to read
              legal documents to understand what&apos;s being decided
            </li>
          </ul>
          <p className="mt-3 text-sm text-gray-500">
            The Voter Quiz, Alignment Matrix, and Voting Blocs focus on the
            current electoral term (2022&ndash;present) to reflect today&apos;s
            Assembly. The full voting archive going back to 2004 is available
            through the Votes and Members pages.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">
            Explore the site
          </h2>
          <p>
            Ahead of the June 2026 States election, Jersey Votes also has a set of
            tools focused on the candidates standing this time:
          </p>
          <ul className="mt-3 space-y-3">
            <li>
              <Link
                href="/candidates"
                className="text-red-700 hover:underline font-medium"
              >
                Candidates
              </Link>{" "}
              &mdash; browse everyone standing in 2026. Each profile sets out the
              candidate&rsquo;s policy positions, extracted from their published
              manifesto and tied to verbatim quotes you can check against the
              original source.
            </li>
            <li>
              <Link
                href="/candidates/quiz"
                className="text-red-700 hover:underline font-medium"
              >
                Voting Quiz
              </Link>{" "}
              &mdash; answer a short set of policy questions and see which
              candidates&rsquo; published positions best match your own
              priorities.
            </li>
            <li>
              <Link
                href="/hustings"
                className="text-red-700 hover:underline font-medium"
              >
                Hustings
              </Link>{" "}
              &mdash; searchable transcripts of the recorded candidate debates,
              broken down by topic, so you can read &mdash; and link to &mdash;
              exactly what was said.
            </li>
            <li>
              <Link
                href="/ask"
                className="text-red-700 hover:underline font-medium"
              >
                Ask
              </Link>{" "}
              &mdash; ask a question about the election in plain English and get an
              answer drawn only from candidates&rsquo; published manifestos and
              hustings statements, with a link to every source. It only answers
              questions about the election and never recommends who to vote for.
            </li>
          </ul>
          <p className="mt-4">
            How candidate positions are extracted and scored, and how the Ask
            feature works end to end, is documented in full on the{" "}
            <Link
              href="/candidates/methodology"
              className="text-red-700 hover:underline font-medium"
            >
              methodology page
            </Link>
            .
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">
            Data source
          </h2>
          <p>
            All voting data is sourced from the{" "}
            <a
              href="https://statesassembly.je/votes"
              target="_blank"
              rel="noopener noreferrer"
              className="text-red-700 hover:underline font-medium"
            >
              States Assembly of Jersey
            </a>
            . Proposition details are linked directly to the official{" "}
            <a
              href="https://statesassembly.je"
              target="_blank"
              rel="noopener noreferrer"
              className="text-red-700 hover:underline font-medium"
            >
              statesassembly.je
            </a>{" "}
            website. We do not editorialise or interpret the data &mdash; the
            analysis is purely mathematical, derived from how members actually
            voted.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">
            Open source
          </h2>
          <p>
            Jersey Votes is fully open source under the{" "}
            <a
              href="https://github.com/gusfraser/jerseyvotes.org/blob/main/LICENSE"
              target="_blank"
              rel="noopener noreferrer"
              className="text-red-700 hover:underline font-medium"
            >
              MIT License
            </a>
            . The code, data pipeline, and analysis tools are all publicly
            available. Contributions, bug reports, and feature suggestions are
            welcome.
          </p>
          <p className="mt-3">
            <a
              href="https://github.com/gusfraser/jerseyvotes.org"
              target="_blank"
              rel="noopener noreferrer"
              className="text-red-700 hover:underline font-medium"
            >
              View on GitHub &rarr;
            </a>
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-3">
            Built by
          </h2>
          <p>
            Jersey Votes was created by <a href="https://www.linkedin.com/in/aonghusfraser/" target="_blank" rel="noopener noreferrer" className="text-red-700 hover:underline font-medium">Gus Fraser</a>, a Jersey resident who believes
            that transparent, accessible political data is essential for a
            healthy democracy.
          </p>
        </section>
      </div>
    </div>
  );
}
