"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { PARISHES, PARISH_DISTRICTS, type Parish } from "@/lib/parish";
import { TranscriptMethodBadge } from "./transcript-method-badge";

type EventRow = {
  event_id: number;
  slug: string;
  title: string;
  role: string | null;
  constituency: string | null;
  event_date: string | null;
  youtube_url: string | null;
  duration_seconds: number | null;
  transcript_method: "hand_cleaned" | "auto_pipeline" | "auto_pipeline_reviewed";
  candidate_count: number;
  question_count: number;
};

// Role order matches the existing page (Connétable → Deputy → Senator).
const ROLES = ["Connétable", "Deputy", "Senator"] as const;
type Role = (typeof ROLES)[number];

/** Parishes an event "belongs to" — used for the parish filter.
 *
 *   - Connétable / Deputy: derive from the canonical constituency string by
 *     looking it up in PARISH_DISTRICTS in reverse (so "Grouville and
 *     St Martin" matches both parishes, "St Helier North" matches St Helier,
 *     etc.).
 *   - Senator: events are titled "Senatorial Hustings 2026 (<location>)", so
 *     pull the parish out of the parens. Senators are island-wide but voters
 *     can still want to find the hustings held in their parish.
 */
function parishesForEvent(ev: EventRow): readonly Parish[] {
  if (ev.role === "Senator") {
    const m = ev.title.match(/\(([^)]+)\)$/);
    if (!m) return [];
    const loc = m[1].trim().toLowerCase();
    const hit = PARISHES.find((p) => p.toLowerCase() === loc);
    return hit ? [hit] : [];
  }
  if (!ev.constituency) return [];
  return PARISHES.filter((p) =>
    PARISH_DISTRICTS[p].includes(ev.constituency as string),
  );
}

export function HustingsFilter({ events }: { events: EventRow[] }) {
  const [role, setRole] = useState<Role | "all">("all");
  const [parish, setParish] = useState<Parish | "all">("all");

  // Pre-compute parish set per event once.
  const eventsWithParishes = useMemo(
    () => events.map((ev) => ({ ev, parishes: parishesForEvent(ev) })),
    [events],
  );

  const filtered = useMemo(() => {
    return eventsWithParishes.filter(({ ev, parishes }) => {
      if (role !== "all" && ev.role !== role) return false;
      if (parish !== "all" && !parishes.includes(parish)) return false;
      return true;
    });
  }, [eventsWithParishes, role, parish]);

  const byRole = useMemo(() => {
    const m = new Map<string, EventRow[]>();
    for (const { ev } of filtered) {
      const r = ev.role ?? "Other";
      if (!m.has(r)) m.set(r, []);
      m.get(r)!.push(ev);
    }
    return m;
  }, [filtered]);

  const sortedRoles = useMemo(() => {
    const order = ROLES as readonly string[];
    return [...byRole.keys()].sort((a, b) => {
      const ai = order.indexOf(a);
      const bi = order.indexOf(b);
      if (ai === -1 && bi === -1) return a.localeCompare(b);
      if (ai === -1) return 1;
      if (bi === -1) return -1;
      return ai - bi;
    });
  }, [byRole]);

  const isFiltered = role !== "all" || parish !== "all";

  return (
    <>
      <section className="mb-8 bg-gray-50 dark:bg-zinc-950 border border-gray-200 dark:border-zinc-800 rounded-lg p-4 sm:p-5">
        <div className="space-y-3">
          <FilterRow
            label="Position"
            options={[
              { value: "all", display: "All" },
              ...ROLES.map((r) => ({ value: r, display: r })),
            ]}
            selected={role}
            onChange={(v) => setRole(v as Role | "all")}
          />
          <FilterRow
            label="Parish"
            options={[
              { value: "all", display: "All" },
              ...PARISHES.map((p) => ({ value: p, display: p })),
            ]}
            selected={parish}
            onChange={(v) => setParish(v as Parish | "all")}
          />
        </div>
        <div className="mt-3 flex items-center justify-between gap-3 text-xs text-gray-500 dark:text-gray-400">
          <span>
            Showing <span className="font-semibold tabular-nums">{filtered.length}</span>{" "}
            of <span className="tabular-nums">{events.length}</span> events
          </span>
          {isFiltered && (
            <button
              type="button"
              onClick={() => {
                setRole("all");
                setParish("all");
              }}
              className="text-red-700 dark:text-red-400 hover:text-red-900 dark:hover:text-red-300 font-medium"
            >
              Clear filters
            </button>
          )}
        </div>
      </section>

      {filtered.length === 0 ? (
        <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-lg p-10 text-center text-gray-500 dark:text-gray-400">
          No hustings match the current filter.
        </div>
      ) : (
        sortedRoles.map((r) => (
          <section key={r} className="mb-10">
            <h2 className="text-lg font-semibold text-gray-700 dark:text-gray-300 mb-3 uppercase tracking-wide">
              {r}
            </h2>
            <div className="grid sm:grid-cols-2 gap-4">
              {byRole.get(r)!.map((ev) => (
                <Link
                  key={ev.event_id}
                  href={`/hustings/${ev.slug}`}
                  className="block bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-lg p-5 hover:border-red-300 hover:shadow-sm transition-all"
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="font-semibold text-gray-900 dark:text-gray-100">
                      {ev.title}
                    </p>
                    <TranscriptMethodBadge method={ev.transcript_method} />
                  </div>
                  {ev.constituency && (
                    <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                      {ev.constituency}
                    </p>
                  )}
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-3">
                    {ev.candidate_count} candidates · {ev.question_count}{" "}
                    audience questions
                    {ev.event_date && (
                      <>
                        {" "}
                        ·{" "}
                        {new Date(ev.event_date).toLocaleDateString("en-GB", {
                          day: "numeric",
                          month: "long",
                          year: "numeric",
                        })}
                      </>
                    )}
                  </p>
                </Link>
              ))}
            </div>
          </section>
        ))
      )}
    </>
  );
}

function FilterRow({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: { value: string; display: string }[];
  selected: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <span className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 min-w-[3.5rem]">
        {label}
      </span>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => {
          const active = o.value === selected;
          return (
            <button
              key={o.value}
              type="button"
              onClick={() => onChange(o.value)}
              aria-pressed={active}
              className={
                active
                  ? "text-xs px-3 py-1.5 rounded-full border bg-red-700 text-white border-red-700"
                  : "text-xs px-3 py-1.5 rounded-full border bg-white dark:bg-zinc-900 text-gray-700 dark:text-gray-200 border-gray-200 dark:border-zinc-700 hover:border-red-300 hover:text-red-700 transition-colors"
              }
            >
              {o.display}
            </button>
          );
        })}
      </div>
    </div>
  );
}
