import Link from "next/link";
import { sql } from "@/lib/db";

export default async function VotesPage({
  searchParams,
}: {
  searchParams: Promise<{ topic?: string; stage?: string; page?: string }>;
}) {
  const { topic, stage, page } = await searchParams;
  const currentPage = Math.max(1, parseInt(page || "1", 10));
  const perPage = 30;
  const offset = (currentPage - 1) * perPage;

  const conditions: string[] = [];
  const params: unknown[] = [];

  let query = `
    SELECT vd.division_id, vd.proposition_title, vd.date, vd.reference,
           vd.pour_count, vd.contre_count, vd.division_stage,
           p.topic_primary, p.source_url, p.plain_language_summary
    FROM vote_divisions vd
    JOIN propositions p ON vd.proposition_id = p.proposition_id
  `;

  let countQuery = `
    SELECT COUNT(*)
    FROM vote_divisions vd
    JOIN propositions p ON vd.proposition_id = p.proposition_id
  `;

  if (topic) {
    conditions.push(`p.topic_primary = $${params.length + 1}`);
    params.push(topic);
  }
  if (stage) {
    conditions.push(`vd.division_stage = $${params.length + 1}`);
    params.push(stage);
  }

  const where =
    conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";
  query += `${where} ORDER BY vd.date DESC LIMIT ${perPage} OFFSET ${offset}`;
  countQuery += where;

  // Use the simpler sql tagged template approach
  let votes, total;
  if (topic && stage) {
    votes = await sql`
      SELECT vd.division_id, vd.proposition_title, vd.date, vd.reference,
             vd.pour_count, vd.contre_count, vd.division_stage,
             p.topic_primary, p.source_url, p.plain_language_summary
      FROM vote_divisions vd
      JOIN propositions p ON vd.proposition_id = p.proposition_id
      WHERE p.topic_primary = ${topic} AND vd.division_stage = ${stage}
      ORDER BY vd.date DESC LIMIT ${perPage} OFFSET ${offset}`;
    const countResult = await sql`
      SELECT COUNT(*) FROM vote_divisions vd
      JOIN propositions p ON vd.proposition_id = p.proposition_id
      WHERE p.topic_primary = ${topic} AND vd.division_stage = ${stage}`;
    total = Number(countResult[0].count);
  } else if (topic) {
    votes = await sql`
      SELECT vd.division_id, vd.proposition_title, vd.date, vd.reference,
             vd.pour_count, vd.contre_count, vd.division_stage,
             p.topic_primary, p.source_url, p.plain_language_summary
      FROM vote_divisions vd
      JOIN propositions p ON vd.proposition_id = p.proposition_id
      WHERE p.topic_primary = ${topic}
      ORDER BY vd.date DESC LIMIT ${perPage} OFFSET ${offset}`;
    const countResult = await sql`
      SELECT COUNT(*) FROM vote_divisions vd
      JOIN propositions p ON vd.proposition_id = p.proposition_id
      WHERE p.topic_primary = ${topic}`;
    total = Number(countResult[0].count);
  } else if (stage) {
    votes = await sql`
      SELECT vd.division_id, vd.proposition_title, vd.date, vd.reference,
             vd.pour_count, vd.contre_count, vd.division_stage,
             p.topic_primary, p.source_url, p.plain_language_summary
      FROM vote_divisions vd
      JOIN propositions p ON vd.proposition_id = p.proposition_id
      WHERE vd.division_stage = ${stage}
      ORDER BY vd.date DESC LIMIT ${perPage} OFFSET ${offset}`;
    const countResult = await sql`
      SELECT COUNT(*) FROM vote_divisions vd
      JOIN propositions p ON vd.proposition_id = p.proposition_id
      WHERE vd.division_stage = ${stage}`;
    total = Number(countResult[0].count);
  } else {
    votes = await sql`
      SELECT vd.division_id, vd.proposition_title, vd.date, vd.reference,
             vd.pour_count, vd.contre_count, vd.division_stage,
             p.topic_primary, p.source_url, p.plain_language_summary
      FROM vote_divisions vd
      JOIN propositions p ON vd.proposition_id = p.proposition_id
      ORDER BY vd.date DESC LIMIT ${perPage} OFFSET ${offset}`;
    const countResult = await sql`
      SELECT COUNT(*) FROM vote_divisions vd
      JOIN propositions p ON vd.proposition_id = p.proposition_id`;
    total = Number(countResult[0].count);
  }

  const totalPages = Math.ceil(total / perPage);

  const topics = await sql`
    SELECT DISTINCT topic_primary FROM propositions
    WHERE topic_primary IS NOT NULL ORDER BY topic_primary`;

  const stages = [
    "principles",
    "third_reading",
    "articles",
    "amendment",
    "paragraph",
    "regulations",
    "procedural",
  ];

  function buildUrl(overrides: Record<string, string | undefined>) {
    const p = new URLSearchParams();
    const vals = { topic, stage, page: "1", ...overrides };
    for (const [k, v] of Object.entries(vals)) {
      if (v) p.set(k, v);
    }
    return `/votes?${p.toString()}`;
  }

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <h1 className="text-3xl font-bold mb-2">Votes</h1>
      <p className="text-gray-500 mb-6">
        {total.toLocaleString()} recorded divisions
      </p>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 mb-6">
        <Link
          href="/votes"
          className={`px-3 py-1.5 rounded-full text-sm ${
            !topic && !stage
              ? "bg-red-700 text-white"
              : "bg-gray-100 text-gray-600 hover:bg-gray-200"
          }`}
        >
          All
        </Link>
        {stages.map((s) => (
          <Link
            key={s}
            href={buildUrl({
              stage: stage === s ? undefined : s,
            })}
            className={`px-3 py-1.5 rounded-full text-sm capitalize ${
              stage === s
                ? "bg-red-700 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {s.replace("_", " ")}
          </Link>
        ))}
      </div>

      <div className="flex flex-wrap gap-1.5 mb-8">
        {topics.map((t: Record<string, unknown>) => (
          <Link
            key={t.topic_primary as string}
            href={buildUrl({
              topic:
                topic === (t.topic_primary as string)
                  ? undefined
                  : (t.topic_primary as string),
            })}
            className={`px-2 py-1 rounded text-xs ${
              topic === (t.topic_primary as string)
                ? "bg-red-700 text-white"
                : "bg-gray-100 text-gray-500 hover:bg-gray-200"
            }`}
          >
            {t.topic_primary as string}
          </Link>
        ))}
      </div>

      {/* Vote list */}
      <div className="space-y-2">
        {votes.map((v: Record<string, unknown>) => {
          const passed =
            (v.pour_count as number) > (v.contre_count as number);
          return (
            <Link
              key={v.division_id as number}
              href={`/votes/${v.division_id}`}
              className="flex items-center gap-4 bg-white rounded-lg border border-gray-200 p-4 hover:border-red-300 transition-colors"
            >
              <div
                className={`w-16 text-center text-sm font-semibold px-2 py-1 rounded ${
                  passed
                    ? "bg-green-50 text-green-700"
                    : "bg-red-50 text-red-700"
                }`}
              >
                {v.pour_count as number}-{v.contre_count as number}
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-medium text-gray-900 truncate">
                  {v.proposition_title as string}
                </p>
                <div className="flex items-center gap-2 mt-1 text-xs text-gray-400">
                  <span>{v.reference as string}</span>
                  <span>
                    {new Date(v.date as string).toLocaleDateString("en-GB", {
                      day: "numeric",
                      month: "short",
                      year: "numeric",
                    })}
                  </span>
                  <span className="capitalize">
                    {(v.division_stage as string).replace("_", " ")}
                  </span>
                  {Boolean(v.topic_primary) && (
                    <span className="bg-gray-100 px-1.5 py-0.5 rounded">
                      {v.topic_primary as string}
                    </span>
                  )}
                </div>
              </div>
            </Link>
          );
        })}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center gap-2 mt-8">
          {currentPage > 1 && (
            <Link
              href={buildUrl({ page: String(currentPage - 1) })}
              className="px-4 py-2 rounded bg-gray-100 text-gray-600 hover:bg-gray-200"
            >
              Previous
            </Link>
          )}
          <span className="px-4 py-2 text-gray-500">
            Page {currentPage} of {totalPages}
          </span>
          {currentPage < totalPages && (
            <Link
              href={buildUrl({ page: String(currentPage + 1) })}
              className="px-4 py-2 rounded bg-gray-100 text-gray-600 hover:bg-gray-200"
            >
              Next
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
