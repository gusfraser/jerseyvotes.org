import type { Metadata } from "next";
import Link from "next/link";
import { sql, daysUntilElection, expandConstituency, PARISHES } from "@/lib/db";

export const metadata: Metadata = {
  title: "Candidates - Jersey 2026 election",
  description:
    "Browse and filter the candidates standing in the 2026 Jersey election. Each candidate's manifesto is analysed against 16 policy topics with verifiable source quotes.",
};

// Render on every request so the "X days until polling day" pill is
// always today's number. See web/src/app/page.tsx for the same rationale.
export const dynamic = "force-dynamic";

type CandidateRow = {
  candidate_id: number;
  vote_je_slug: string;
  full_name: string;
  role: string | null;
  constituency: string | null;
  party: string | null;
  photo_url: string | null;
  incumbent_member_id: number | null;
  scrape_status: string;
  classified_at: string | null;
  manifesto_word_count: number | null;
  enhanced_manifesto_status: string | null;
  topics: string[] | null;
};

type SearchParams = {
  constituency?: string;
  role?: string;
  party?: string;
  topic?: string;
  q?: string;
};

export default async function CandidatesPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const constituency = params.constituency?.trim() || null;
  const role = params.role?.trim() || null;
  const party = params.party?.trim() || null;
  const topic = params.topic?.trim() || null;
  const search = params.q?.trim() || null;

  // Parish → list-of-constituencies expansion. Picking "St Helier" should
  // return Connétable + 3 Deputy districts + all Senators; picking a literal
  // district stays exact. See web/src/lib/db.ts:expandConstituency.
  const expansion = expandConstituency(constituency);
  const constituencyList = expansion.constituencies;       // null = no filter
  const includeSenators = expansion.includeSenators;
  const isParishFilter = constituency !== null && (PARISHES as readonly string[]).includes(constituency);

  const candidates = (await sql`
    SELECT c.candidate_id, c.vote_je_slug, c.full_name, c.role, c.constituency,
           c.party, c.photo_url, c.incumbent_member_id, c.scrape_status,
           c.classified_at, c.manifesto_word_count, c.enhanced_manifesto_status,
           ARRAY(
             SELECT topic FROM candidate_topics ct
             WHERE ct.candidate_id = c.candidate_id
             ORDER BY ct.salience DESC LIMIT 4
           ) AS topics
    FROM candidates c
    WHERE c.election_year = 2026
      AND c.opted_out_at IS NULL
      AND (
        ${constituencyList === null}::boolean
        OR c.constituency = ANY(${constituencyList ?? []}::text[])
        OR (${includeSenators}::boolean AND c.role = 'Senator')
      )
      AND (${role}::text IS NULL OR c.role = ${role})
      AND (${party}::text IS NULL OR c.party = ${party})
      AND (${search}::text IS NULL OR c.full_name ILIKE ${"%" + (search ?? "") + "%"})
      AND (
        ${topic}::text IS NULL
        OR EXISTS (
          SELECT 1 FROM candidate_topics ct
          WHERE ct.candidate_id = c.candidate_id AND ct.topic = ${topic}
        )
      )
    ORDER BY c.full_name
  `) as unknown as CandidateRow[];

  const filterOptions = await sql`
    SELECT
      ARRAY(SELECT DISTINCT constituency FROM candidates WHERE election_year = 2026 AND opted_out_at IS NULL AND constituency IS NOT NULL ORDER BY 1) AS constituencies,
      ARRAY(SELECT DISTINCT role FROM candidates WHERE election_year = 2026 AND opted_out_at IS NULL AND role IS NOT NULL ORDER BY 1) AS roles,
      ARRAY(SELECT DISTINCT party FROM candidates WHERE election_year = 2026 AND opted_out_at IS NULL AND party IS NOT NULL ORDER BY 1) AS parties,
      ARRAY(SELECT DISTINCT topic FROM candidate_topics ORDER BY 1) AS topics
  `;
  const opts = filterOptions[0] as Record<string, string[]>;
  const days = daysUntilElection();
  const activeFilters = [constituency, role, party, topic, search].filter(Boolean).length;

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <header className="mb-8">
        <div className="flex flex-wrap items-baseline justify-between gap-3 mb-3">
          <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">
            Candidates
          </h1>
          {days > 0 && (
            <span className="text-sm text-gray-500 dark:text-gray-400">
              {days} {days === 1 ? "day" : "days"} until polling day
            </span>
          )}
        </div>
        <p className="text-gray-500 dark:text-gray-400 max-w-3xl">
          {candidates.length} {activeFilters > 0 ? "matching" : "candidates"} standing in the 2026 Jersey election.
          {isParishFilter && (
            <>
              {" "}Showing everyone a voter in <strong>{constituency}</strong> can vote for.
              On polling day you pick <strong>up to 9 Senators</strong> (island-wide),{" "}
              <strong>1 Connétable</strong> for your parish, and{" "}
              <strong>2&ndash;4 Deputies</strong> depending on your constituency
              (
              <a
                href="https://www.vote.je/constituency-finder/"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-red-700"
              >
                look up your constituency
              </a>
              ).
            </>
          )}{" "}
          Each manifesto has been classified against{" "}
          <Link href="/candidates/methodology" className="underline hover:text-red-700">
            16 policy topics
          </Link>{" "}
          with verifiable source quotes.{" "}
          <Link href="/candidates/quiz" className="text-red-700 underline hover:no-underline font-medium">
            Take the quiz &rarr;
          </Link>
        </p>
      </header>

      {/* Filters */}
      <form
        method="GET"
        className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-3 mb-6 bg-gray-50 dark:bg-zinc-950 border border-gray-200 dark:border-zinc-800 rounded-lg p-4"
      >
        <FilterSelect
          label="Constituency"
          name="constituency"
          value={constituency}
          options={opts.constituencies ?? []}
        />
        <FilterSelect
          label="Role"
          name="role"
          value={role}
          options={opts.roles ?? []}
        />
        <FilterSelect
          label="Party"
          name="party"
          value={party}
          options={opts.parties ?? []}
        />
        <FilterSelect
          label="Topic addressed"
          name="topic"
          value={topic}
          options={opts.topics ?? []}
        />
        <div className="flex flex-col gap-1">
          <label htmlFor="q" className="text-xs text-gray-500 dark:text-gray-400">
            Name
          </label>
          <input
            id="q"
            name="q"
            defaultValue={search ?? ""}
            placeholder="Search&hellip;"
            className="text-sm px-3 py-2 rounded-md border border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-gray-900 dark:text-gray-100"
          />
        </div>

        <div className="sm:col-span-2 md:col-span-5 flex gap-2 justify-end">
          {activeFilters > 0 && (
            <Link
              href="/candidates"
              className="text-sm px-4 py-2 text-gray-500 dark:text-gray-400 hover:text-red-700"
            >
              Clear filters
            </Link>
          )}
          <button
            type="submit"
            className="text-sm px-4 py-2 bg-red-700 text-white rounded-md hover:bg-red-800 font-medium"
          >
            Apply
          </button>
        </div>
      </form>

      {/* Candidate grid */}
      {candidates.length === 0 ? (
        <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-lg p-10 text-center text-gray-500 dark:text-gray-400">
          No candidates match these filters.
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {candidates.map((c) => (
            <CandidateCard key={c.candidate_id} c={c} />
          ))}
        </div>
      )}

      {/* Contact footer — applies to questions about any candidate */}
      <div className="mt-12 pt-6 border-t border-gray-200 dark:border-zinc-800 text-sm text-gray-600 dark:text-gray-400 text-center">
        Spot an error on a candidate&rsquo;s page, or want to suggest an
        improvement? Email{" "}
        <a
          href={`mailto:gus@helix.je?subject=${encodeURIComponent("Jersey Votes — candidate matcher")}`}
          className="text-red-700 underline hover:no-underline"
        >
          gus@helix.je
        </a>
        . Most corrections processed within 24 hours.
      </div>
    </div>
  );
}

function FilterSelect({
  label,
  name,
  value,
  options,
}: {
  label: string;
  name: string;
  value: string | null;
  options: string[];
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={name} className="text-xs text-gray-500 dark:text-gray-400">
        {label}
      </label>
      <select
        id={name}
        name={name}
        defaultValue={value ?? ""}
        className="text-sm px-3 py-2 rounded-md border border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-gray-900 dark:text-gray-100"
      >
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </div>
  );
}

function CandidateCard({ c }: { c: CandidateRow }) {
  const isIncumbent = c.incumbent_member_id !== null;
  const hasEnhanced = c.enhanced_manifesto_status === "found";
  const isLowContent = c.scrape_status === "low_content" && !hasEnhanced;
  const topics = (c.topics ?? []).filter(Boolean);

  return (
    <Link
      href={`/candidates/${c.vote_je_slug}`}
      className="block bg-white dark:bg-zinc-900 rounded-lg border border-gray-200 dark:border-zinc-800 p-4 hover:border-red-300 hover:shadow-sm transition-all"
    >
      <div className="flex gap-4">
        <div className="w-16 h-16 flex-shrink-0 rounded-lg overflow-hidden bg-gray-100 dark:bg-zinc-800">
          {c.photo_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={c.photo_url}
              alt={c.full_name}
              className="w-full h-full object-cover"
              loading="lazy"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-gray-400 text-2xl font-light">
              {c.full_name.charAt(0)}
            </div>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-gray-900 dark:text-gray-100 truncate">
            {c.full_name}
          </p>
          <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400 mt-0.5 flex-wrap">
            {c.role && <span>{c.role}</span>}
            {(c.constituency || c.role === "Senator") && <span>·</span>}
            {c.constituency ? (
              <span className="truncate">{c.constituency}</span>
            ) : c.role === "Senator" ? (
              <span className="truncate italic">island-wide</span>
            ) : null}
          </div>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            {c.party && (
              <span className="text-xs bg-gray-100 dark:bg-zinc-800 text-gray-700 dark:text-gray-300 px-1.5 py-0.5 rounded">
                {c.party}
              </span>
            )}
            {isIncumbent && (
              <span className="text-xs bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300 px-1.5 py-0.5 rounded">
                Incumbent
              </span>
            )}
            {isLowContent && (
              <span className="text-xs bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 px-1.5 py-0.5 rounded">
                Short manifesto
              </span>
            )}
            {hasEnhanced && (
              <span className="text-xs bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 px-1.5 py-0.5 rounded">
                Extended manifesto
              </span>
            )}
          </div>
        </div>
      </div>
      {topics.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {topics.map((t) => (
            <span
              key={t}
              className="text-xs text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-zinc-950 border border-gray-100 dark:border-zinc-800 px-2 py-0.5 rounded"
            >
              {t}
            </span>
          ))}
        </div>
      )}
    </Link>
  );
}
