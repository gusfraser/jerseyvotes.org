import type { Metadata } from "next";
import Link from "next/link";
import { sql } from "@/lib/db";
import { slugify } from "@/lib/slugify";

export const metadata: Metadata = {
  title: "Members",
  description:
    "Browse voting records for all 158 Jersey States Assembly members from 2004 to present, including 49 currently active members.",
};

export default async function MembersPage() {
  // Attendance is computed per sitting day (not per division): a sitting often
  // holds many separate votes, so counting missed votes would overstate
  // absence. A member counts as present for a day if they cast >= 1 active vote.
  const members = await sql`
    WITH member_days AS (
      SELECT v.member_id, vd.date::date AS d,
             MAX((v.vote_category = 'active_vote')::int) AS attended
      FROM votes v
      JOIN vote_divisions vd ON v.division_id = vd.division_id
      GROUP BY v.member_id, vd.date::date
    ),
    sessions AS (
      SELECT member_id,
             COUNT(*) AS sitting_days,
             SUM(attended) AS sessions_attended
      FROM member_days
      GROUP BY member_id
    )
    SELECT m.member_id, m.canonical_name, m.display_name,
           m.is_currently_active, m.position_history,
           m.first_vote_date::date as first_date,
           m.last_vote_date::date as last_date,
           COUNT(CASE WHEN v.vote_category = 'active_vote' THEN 1 END) as active_votes,
           COALESCE(s.sitting_days, 0) as sitting_days,
           COALESCE(s.sessions_attended, 0) as sessions_attended
    FROM members m
    LEFT JOIN votes v ON m.member_id = v.member_id
    LEFT JOIN sessions s ON s.member_id = m.member_id
    GROUP BY m.member_id, s.sitting_days, s.sessions_attended
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
  const attendance =
    (m.sitting_days as number) > 0
      ? ((m.sessions_attended as number) / (m.sitting_days as number)) * 100
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
            {attendance.toFixed(0)}%
          </p>
          <p className="text-gray-400">Attendance</p>
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
