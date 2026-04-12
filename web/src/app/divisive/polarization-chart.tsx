"use client";

import { useState } from "react";

type YearData = {
  year: number;
  avgCloseness: number;
  voteCount: number;
};

const ELECTION_YEARS = [2005, 2008, 2011, 2014, 2018, 2022];

export function PolarizationChart({ data }: { data: YearData[] }) {
  const [hovered, setHovered] = useState<YearData | null>(null);

  if (data.length === 0) return null;

  const padding = { top: 20, right: 30, bottom: 40, left: 50 };
  const width = 800;
  const height = 300;
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  const minYear = data[0].year;
  const maxYear = data[data.length - 1].year;
  const yearRange = maxYear - minYear || 1;

  const maxVal = Math.max(...data.map((d) => d.avgCloseness));
  const yMax = Math.ceil(maxVal * 100 / 5) * 5; // round up to nearest 5%

  function x(year: number) {
    return padding.left + ((year - minYear) / yearRange) * chartW;
  }
  function y(val: number) {
    return padding.top + chartH - (val / (yMax / 100)) * chartH;
  }

  // Build line path
  const linePath = data
    .map((d, i) => `${i === 0 ? "M" : "L"}${x(d.year)},${y(d.avgCloseness)}`)
    .join(" ");

  // Area path (fill under line)
  const areaPath =
    linePath +
    ` L${x(data[data.length - 1].year)},${y(0)} L${x(data[0].year)},${y(0)} Z`;

  // Y-axis grid lines
  const yTicks = [];
  for (let i = 0; i <= yMax; i += 5) {
    yTicks.push(i);
  }

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full max-w-4xl bg-white rounded-lg border border-gray-200">
        {/* Y-axis grid lines */}
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              x1={padding.left}
              y1={y(tick / 100)}
              x2={width - padding.right}
              y2={y(tick / 100)}
              stroke="#f3f4f6"
              strokeWidth={1}
            />
            <text
              x={padding.left - 8}
              y={y(tick / 100) + 4}
              textAnchor="end"
              fontSize={10}
              fill="#9ca3af"
            >
              {tick}%
            </text>
          </g>
        ))}

        {/* Election year markers */}
        {ELECTION_YEARS.filter((yr) => yr >= minYear && yr <= maxYear).map(
          (yr) => (
            <g key={`election-${yr}`}>
              <line
                x1={x(yr)}
                y1={padding.top}
                x2={x(yr)}
                y2={padding.top + chartH}
                stroke="#dc2626"
                strokeWidth={1}
                strokeDasharray="4 4"
                opacity={0.4}
              />
              <text
                x={x(yr)}
                y={padding.top - 6}
                textAnchor="middle"
                fontSize={8}
                fill="#dc2626"
                opacity={0.6}
              >
                Election
              </text>
            </g>
          )
        )}

        {/* Area fill */}
        <path d={areaPath} fill="#dc2626" opacity={0.08} />

        {/* Line */}
        <path
          d={linePath}
          fill="none"
          stroke="#dc2626"
          strokeWidth={2.5}
          strokeLinejoin="round"
        />

        {/* Data points */}
        {data.map((d) => (
          <circle
            key={d.year}
            cx={x(d.year)}
            cy={y(d.avgCloseness)}
            r={hovered?.year === d.year ? 6 : 4}
            fill={hovered?.year === d.year ? "#dc2626" : "#fff"}
            stroke="#dc2626"
            strokeWidth={2}
            className="cursor-pointer"
            onMouseEnter={() => setHovered(d)}
            onMouseLeave={() => setHovered(null)}
          />
        ))}

        {/* X-axis labels */}
        {data
          .filter((_, i) => i % 2 === 0 || data.length <= 12)
          .map((d) => (
            <text
              key={`x-${d.year}`}
              x={x(d.year)}
              y={height - 8}
              textAnchor="middle"
              fontSize={10}
              fill="#9ca3af"
            >
              {d.year}
            </text>
          ))}

        {/* Axis labels */}
        <text
          x={padding.left - 8}
          y={padding.top + chartH + 4}
          textAnchor="end"
          fontSize={9}
          fill="#9ca3af"
          transform={`rotate(-90, ${padding.left - 8}, ${padding.top + chartH / 2})`}
        >
          Avg. minority %
        </text>
      </svg>

      {/* Tooltip */}
      {hovered && (
        <div
          className="absolute bg-gray-900 text-white text-xs px-3 py-2 rounded shadow-lg pointer-events-none z-50 whitespace-nowrap"
          style={{
            left: `${((x(hovered.year) / width) * 100)}%`,
            top: `${((y(hovered.avgCloseness) / height) * 100) - 12}%`,
            transform: "translateX(-50%)",
          }}
        >
          <strong>{hovered.year}</strong>: {(hovered.avgCloseness * 100).toFixed(1)}% avg. minority ({hovered.voteCount} votes)
        </div>
      )}
    </div>
  );
}
