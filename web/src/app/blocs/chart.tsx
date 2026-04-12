"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";

type MemberPoint = {
  name: string;
  x: number;
  y: number;
  bloc: number;
};

type TopicInfo = {
  name: string;
  count: number;
};

type BlocsData = {
  members: MemberPoint[];
  topics: TopicInfo[];
  divisionCount: number;
};

const BLOC_COLORS = [
  "#dc2626", // red
  "#2563eb", // blue
  "#16a34a", // green
  "#d97706", // amber
  "#7c3aed", // violet
  "#0891b2", // cyan
];

function slugify(name: string): string {
  return name
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

export function BlocsChart() {
  const [data, setData] = useState<BlocsData | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [selectedTopics, setSelectedTopics] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const fetchData = useCallback((topics: string[]) => {
    setLoading(true);
    const params = topics.length > 0 ? `?topics=${encodeURIComponent(topics.join("|"))}` : "";
    fetch(`/api/blocs${params}`)
      .then((r) => r.json())
      .then((d) => {
        setData(d);
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    fetchData([]);
  }, [fetchData]);

  function toggleTopic(topic: string) {
    const next = selectedTopics.includes(topic)
      ? selectedTopics.filter((t) => t !== topic)
      : [...selectedTopics, topic];
    setSelectedTopics(next);
    fetchData(next);
  }

  function clearTopics() {
    setSelectedTopics([]);
    fetchData([]);
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center h-96 text-gray-400">
        Computing political positions...
      </div>
    );
  }

  const members = data.members;
  const topics = data.topics || [];

  // Compute bounds
  const xs = members.map((d) => d.x);
  const ys = members.map((d) => d.y);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const xRange = xMax - xMin || 1;
  const yRange = yMax - yMin || 1;
  const padding = 60;
  const width = 800;
  const height = 600;

  function scaleX(v: number) {
    return padding + ((v - xMin) / xRange) * (width - 2 * padding);
  }
  function scaleY(v: number) {
    return height - padding - ((v - yMin) / yRange) * (height - 2 * padding);
  }

  // Group by bloc
  const blocs: Record<number, MemberPoint[]> = {};
  for (const m of members) {
    if (!blocs[m.bloc]) blocs[m.bloc] = [];
    blocs[m.bloc].push(m);
  }

  return (
    <div>
      {/* Topic filter */}
      <div className="mb-6 relative">
        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="bg-white border border-gray-300 rounded-lg px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors flex items-center gap-2"
          >
            Filter by topic
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          {selectedTopics.length > 0 && (
            <>
              {selectedTopics.map((t) => (
                <span
                  key={t}
                  className="inline-flex items-center gap-1 bg-red-50 text-red-700 text-sm px-3 py-1 rounded-full"
                >
                  {t}
                  <button
                    onClick={() => toggleTopic(t)}
                    className="hover:text-red-900"
                  >
                    &times;
                  </button>
                </span>
              ))}
              <button
                onClick={clearTopics}
                className="text-sm text-gray-500 hover:text-gray-700"
              >
                Clear all
              </button>
            </>
          )}
          {selectedTopics.length === 0 && (
            <span className="text-sm text-gray-400">
              Showing all topics ({data.divisionCount} votes)
            </span>
          )}
          {selectedTopics.length > 0 && (
            <span className={`text-sm ${data.divisionCount < 15 ? "text-amber-600" : "text-gray-400"}`}>
              {data.divisionCount} votes in selected topics
              {data.divisionCount < 15 && " — small sample, positions may be less reliable"}
            </span>
          )}
          {loading && (
            <span className="text-sm text-gray-400 animate-pulse">
              Recalculating...
            </span>
          )}
        </div>
        {dropdownOpen && (
          <div className="absolute z-20 mt-2 bg-white border border-gray-200 rounded-lg shadow-lg p-2 max-h-80 overflow-y-auto w-72">
            {topics.map((t) => (
              <label
                key={t.name}
                className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 rounded cursor-pointer text-sm"
              >
                <input
                  type="checkbox"
                  checked={selectedTopics.includes(t.name)}
                  onChange={() => toggleTopic(t.name)}
                  className="rounded border-gray-300 text-red-700 focus:ring-red-500"
                />
                <span className="flex-1 text-gray-700">{t.name}</span>
                <span className="text-gray-400 tabular-nums">{t.count}</span>
              </label>
            ))}
          </div>
        )}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full max-w-4xl bg-white rounded-lg border border-gray-200">
        {/* Axes */}
        <line
          x1={padding}
          y1={height / 2}
          x2={width - padding}
          y2={height / 2}
          stroke="#e5e7eb"
          strokeDasharray="4 4"
        />
        <line
          x1={width / 2}
          y1={padding}
          x2={width / 2}
          y2={height - padding}
          stroke="#e5e7eb"
          strokeDasharray="4 4"
        />

        {/* Points */}
        {members.map((m) => {
          const cx = scaleX(m.x);
          const cy = scaleY(m.y);
          const isHovered = hovered === m.name;
          return (
            <g key={m.name}>
              <a href={`/members/${slugify(m.name)}`}>
                {/* Larger invisible hit area for easier hover */}
                <circle
                  cx={cx}
                  cy={cy}
                  r={16}
                  fill="transparent"
                  onMouseEnter={() => setHovered(m.name)}
                  onMouseLeave={() => setHovered(null)}
                  className="cursor-pointer"
                />
                <circle
                  cx={cx}
                  cy={cy}
                  r={isHovered ? 8 : 6}
                  fill={BLOC_COLORS[m.bloc % BLOC_COLORS.length]}
                  opacity={hovered && !isHovered ? 0.3 : 0.85}
                  stroke="white"
                  strokeWidth={1.5}
                  className="pointer-events-none transition-all duration-150"
                />
                {/* Label - always visible, highlighted on hover */}
                {isHovered ? (
                  <>
                    <rect
                      x={cx + 10}
                      y={cy - 10}
                      width={m.name.length * 7 + 8}
                      height={20}
                      rx={4}
                      fill="rgba(0,0,0,0.85)"
                      className="pointer-events-none"
                    />
                    <text
                      x={cx + 14}
                      y={cy + 4}
                      fontSize={12}
                      fill="white"
                      fontWeight="bold"
                      className="pointer-events-none"
                    >
                      {m.name}
                    </text>
                  </>
                ) : (
                  <text
                    x={cx + 9}
                    y={cy + 3}
                    fontSize={8}
                    fill={hovered ? "#bbb" : "#555"}
                    className="pointer-events-none"
                  >
                    {m.name.split(" ").slice(-1)[0]}
                  </text>
                )}
              </a>
            </g>
          );
        })}

        {/* Axis labels */}
        <text
          x={width / 2}
          y={height - padding + 28}
          textAnchor="middle"
          fontSize={11}
          fill="#9ca3af"
        >
          &larr; Main voting divide &rarr;
        </text>
        <text
          x={padding - 8}
          y={height / 2}
          textAnchor="middle"
          fontSize={11}
          fill="#9ca3af"
          transform={`rotate(-90, ${padding - 8}, ${height / 2})`}
        >
          &larr; Secondary voting divide &rarr;
        </text>
      </svg>

      {/* Legend */}
      <div className="mt-8 grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {Object.entries(blocs)
          .sort((a, b) => b[1].length - a[1].length)
          .map(([blocId, members]) => (
            <div
              key={blocId}
              className="bg-white rounded-lg border border-gray-200 p-4"
            >
              <div className="flex items-center gap-2 mb-2">
                <div
                  className="w-3 h-3 rounded-full"
                  style={{
                    backgroundColor:
                      BLOC_COLORS[Number(blocId) % BLOC_COLORS.length],
                  }}
                />
                <span className="font-semibold text-gray-900">
                  Bloc {Number(blocId) + 1} ({members.length} members)
                </span>
              </div>
              <div className="flex flex-wrap gap-1">
                {members
                  .sort((a, b) => a.name.localeCompare(b.name))
                  .map((m) => (
                    <Link
                      key={m.name}
                      href={`/members/${slugify(m.name)}`}
                      className="text-sm text-gray-800 bg-gray-100 px-2.5 py-1 rounded-md hover:bg-gray-200 transition-colors"
                    >
                      {m.name}
                    </Link>
                  ))}
              </div>
            </div>
          ))}
      </div>
    </div>
  );
}
