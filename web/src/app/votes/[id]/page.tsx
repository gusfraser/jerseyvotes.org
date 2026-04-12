import Link from "next/link";
import { notFound } from "next/navigation";
import { sql } from "@/lib/db";
import { slugify } from "@/lib/slugify";

export default async function VotePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const divisionId = parseInt(id, 10);
  if (isNaN(divisionId)) notFound();

  const [divisions, votes] = await Promise.all([
    sql`SELECT vd.*, p.base_reference, p.source_url, p.topic_primary,
             p.plain_language_summary, p.topic_tags
           FROM vote_divisions vd
           JOIN propositions p ON vd.proposition_id = p.proposition_id
           WHERE vd.division_id = ${divisionId}`,
    sql`SELECT v.vote, v.vote_category, m.canonical_name, m.display_name,
             m.position_history
           FROM votes v
           JOIN members m ON v.member_id = m.member_id
           WHERE v.division_id = ${divisionId}
           ORDER BY v.vote, m.canonical_name`,
  ]);

  if (divisions.length === 0) notFound();
  const division = divisions[0];

  const voteGroups: Record<string, Record<string, unknown>[]> = {};
  for (const v of votes) {
    const vote = v.vote as string;
    if (!voteGroups[vote]) voteGroups[vote] = [];
    voteGroups[vote].push(v);
  }

  const passed =
    (division.pour_count as number) > (division.contre_count as number);

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <Link
        href="/votes"
        className="text-sm text-gray-500 hover:text-red-700 mb-4 inline-block"
      >
        &larr; All Votes
      </Link>

      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold mb-2">
          {division.proposition_title as string}
        </h1>
        {division.plain_language_summary && (
          <p className="text-lg text-gray-600 mb-3">
            {division.plain_language_summary as string}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3 text-sm text-gray-500">
          <span>{division.reference as string}</span>
          <span>
            {new Date(division.date as string).toLocaleDateString("en-GB", {
              weekday: "long",
              day: "numeric",
              month: "long",
              year: "numeric",
            })}
          </span>
          <span className="capitalize bg-gray-100 px-2 py-0.5 rounded">
            {(division.division_stage as string).replace("_", " ")}
          </span>
          {division.topic_primary && (
            <span className="bg-red-50 text-red-700 px-2 py-0.5 rounded">
              {division.topic_primary as string}
            </span>
          )}
          {division.source_url && (
            <a
              href={division.source_url as string}
              target="_blank"
              rel="noopener noreferrer"
              className="text-red-700 hover:underline"
            >
              View on States Assembly &rarr;
            </a>
          )}
        </div>
      </div>

      {/* Result banner */}
      <div
        className={`rounded-lg p-6 mb-8 ${
          passed ? "bg-green-50 border border-green-200" : "bg-red-50 border border-red-200"
        }`}
      >
        <div className="flex items-center justify-between">
          <div>
            <p
              className={`text-2xl font-bold ${
                passed ? "text-green-700" : "text-red-700"
              }`}
            >
              {passed ? "Adopted" : "Rejected"}
            </p>
            <p className="text-sm text-gray-600 mt-1">
              {division.pour_count as number} Pour &middot;{" "}
              {division.contre_count as number} Contre &middot;{" "}
              {division.abstain_count as number} Abstained
            </p>
          </div>
          <div className="text-4xl font-bold text-gray-300">
            {division.pour_count as number}-{division.contre_count as number}
          </div>
        </div>
      </div>

      {/* Vote breakdown */}
      <div className="grid md:grid-cols-3 gap-6 bg-white rounded-lg border border-gray-200 p-6">
        <VoteGroup
          label="Pour"
          votes={voteGroups["Pour"] || []}
          color="green"
        />
        <VoteGroup
          label="Contre"
          votes={voteGroups["Contre"] || []}
          color="red"
        />
        <div>
          <VoteGroup
            label="Abstained"
            votes={voteGroups["Abstained"] || []}
            color="yellow"
          />
          <VoteGroup
            label="Not Present"
            votes={[
              ...(voteGroups["Not present for vote"] || []),
              ...(voteGroups["En d\u00e9faut"] || []),
            ]}
            color="gray"
          />
          <VoteGroup
            label="Other"
            votes={[
              ...(voteGroups["Ill"] || []),
              ...(voteGroups["Out of the Island"] || []),
              ...(voteGroups["Excused attendance"] || []),
              ...(voteGroups["Declared an interest"] || []),
              ...(voteGroups["Suspended"] || []),
              ...(voteGroups["Parental responsibilities"] || []),
              ...(voteGroups["Presiding"] || []),
            ]}
            color="gray"
          />
        </div>
      </div>
    </div>
  );
}

function VoteGroup({
  label,
  votes,
  color,
}: {
  label: string;
  votes: Record<string, unknown>[];
  color: string;
}) {
  if (votes.length === 0) return null;

  const colorMap: Record<string, string> = {
    green: "bg-green-100 text-green-800",
    red: "bg-red-100 text-red-800",
    yellow: "bg-yellow-100 text-yellow-800",
    gray: "bg-gray-100 text-gray-600",
  };

  return (
    <div className="mb-6">
      <h3 className="font-semibold text-gray-900 mb-2">
        {label}{" "}
        <span className="text-gray-400 font-normal">({votes.length})</span>
      </h3>
      <div className="flex flex-wrap gap-1.5">
        {votes.map((v) => {
          const positions = v.position_history as {
            position: string;
            count: number;
          }[];
          const pos = positions?.[0]?.position ?? "";
          return (
            <Link
              key={v.canonical_name as string}
              href={`/members/${slugify(v.canonical_name as string)}`}
              className={`text-xs px-2 py-1 rounded ${colorMap[color]} hover:opacity-80 transition-opacity`}
              title={`${pos} ${v.display_name}`}
            >
              {v.display_name as string}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
