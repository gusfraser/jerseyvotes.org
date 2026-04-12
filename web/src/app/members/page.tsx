import Link from "next/link";
import { sql } from "@/lib/db";
import { slugify } from "@/lib/slugify";

export default async function MembersPage() {
  const members = await sql`
    SELECT m.member_id, m.canonical_name, m.display_name,
           m.is_currently_active, m.position_history,
           m.first_vote_date::date as first_date,
           m.last_vote_date::date as last_date,
           COUNT(CASE WHEN v.vote_category = 'active_vote' THEN 1 END) as active_votes,
           COUNT(*) as total_divisions,
           COUNT(CASE WHEN v.vote = 'Pour' THEN 1 END) as pour_count,
           COUNT(CASE WHEN v.vote = 'Contre' THEN 1 END) as contre_count
    FROM members m
    LEFT JOIN votes v ON m.member_id = v.member_id
    GROUP BY m.member_id
    ORDER BY m.is_currently_active DESC, m.canonical_name
  `;

  const active = members.filter(
    (m: Record<string, unknown>) => m.is_currently_active
  );
  const former = members.filter(
    (m: Record<string, unknown>) => !m.is_currently_active
  );

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <h1 className="text-3xl font-bold mb-2">Members</h1>
      <p className="text-gray-500 mb-8">
        {active.length} currently active members, {former.length} former members
      </p>

      <h2 className="text-xl font-semibold mb-4">Current Members</h2>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-12">
        {active.map((m: Record<string, unknown>) => (
          <MemberCard key={m.member_id as number} member={m} />
        ))}
      </div>

      <h2 className="text-xl font-semibold mb-4">Former Members</h2>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {former.map((m: Record<string, unknown>) => (
          <MemberCard key={m.member_id as number} member={m} />
        ))}
      </div>
    </div>
  );
}

function MemberCard({ member: m }: { member: Record<string, unknown> }) {
  const positions = m.position_history as { position: string; count: number }[];
  const mainPosition = positions?.[0]?.position ?? "Member";
  const participation =
    (m.total_divisions as number) > 0
      ? ((m.active_votes as number) / (m.total_divisions as number)) * 100
      : 0;

  return (
    <Link
      href={`/members/${slugify(m.canonical_name as string)}`}
      className="bg-white rounded-lg border border-gray-200 p-4 hover:border-red-300 hover:shadow-sm transition-all"
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="font-semibold text-gray-900">
            {m.display_name as string}
          </p>
          <p className="text-sm text-gray-500">{mainPosition}</p>
        </div>
        {Boolean(m.is_currently_active) && (
          <span className="bg-green-100 text-green-700 text-xs px-2 py-0.5 rounded-full">
            Active
          </span>
        )}
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
        <div>
          <p className="font-semibold text-gray-900">
            {Number(m.active_votes).toLocaleString()}
          </p>
          <p className="text-gray-400">Votes</p>
        </div>
        <div>
          <p className="font-semibold text-gray-900">
            {participation.toFixed(0)}%
          </p>
          <p className="text-gray-400">Participation</p>
        </div>
        <div>
          <p className="font-semibold text-gray-900">
            {new Date(m.first_date as string).getFullYear()}&ndash;
            {new Date(m.last_date as string).getFullYear()}
          </p>
          <p className="text-gray-400">Years</p>
        </div>
      </div>
    </Link>
  );
}
