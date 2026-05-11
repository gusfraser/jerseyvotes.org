import { NextResponse } from "next/server";
import { sql } from "@/lib/db";

// Receives candidate correction submissions. Writes the submission to the
// candidate record's correction_state and stores the raw body in a notes
// column on the candidate (which we add lazily here). Email notification is
// not handled in code — the maintainer pulls from this table during the
// review window. Keeping it simple to avoid an SMTP dependency.

export async function POST(
  request: Request,
  ctx: { params: Promise<{ token: string }> },
) {
  const { token } = await ctx.params;
  if (!token) {
    return NextResponse.json({ error: "Missing token" }, { status: 400 });
  }

  let body: { body?: string; contact?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }
  const note = (body.body ?? "").trim();
  const contact = (body.contact ?? "").trim();
  if (!note) {
    return NextResponse.json({ error: "Missing body" }, { status: 400 });
  }
  if (note.length > 5000 || contact.length > 320) {
    return NextResponse.json({ error: "Too long" }, { status: 413 });
  }

  // Lazily ensure the notes column exists. ALTER IF NOT EXISTS is cheap.
  await sql`
    ALTER TABLE candidates
    ADD COLUMN IF NOT EXISTS correction_notes JSONB DEFAULT '[]'::jsonb
  `;

  const rows = (await sql`
    SELECT candidate_id FROM candidates WHERE correction_token = ${token} LIMIT 1
  `) as { candidate_id: number }[];
  if (rows.length === 0) {
    return NextResponse.json({ error: "Unknown token" }, { status: 404 });
  }
  const candidateId = rows[0].candidate_id;

  const entry = {
    submitted_at: new Date().toISOString(),
    contact,
    note,
  };

  await sql`
    UPDATE candidates
    SET correction_state = 'disputed',
        correction_notes = COALESCE(correction_notes, '[]'::jsonb) || ${JSON.stringify(entry)}::jsonb
    WHERE candidate_id = ${candidateId}
  `;

  return NextResponse.json({ ok: true });
}
