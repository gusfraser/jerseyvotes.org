"use client";

import { useEffect, useState, useRef } from "react";

type AlignmentData = {
  names: string[];
  matrix: number[][];
  sharedCounts: number[][];
};

function getColor(value: number): string {
  // 0.85 (low agreement) -> red, 0.925 (mid) -> yellow, 1.0 (high) -> green
  const min = 0.85;
  const max = 1.0;
  const clamped = Math.max(min, Math.min(max, value));
  const t = (clamped - min) / (max - min); // 0 to 1

  if (t < 0.5) {
    // red to yellow
    const r = 220;
    const g = Math.round(60 + t * 2 * 160);
    const b = 60;
    return `rgb(${r},${g},${b})`;
  } else {
    // yellow to green
    const r = Math.round(220 - (t - 0.5) * 2 * 170);
    const g = Math.round(180 + (t - 0.5) * 2 * 40);
    const b = 60;
    return `rgb(${r},${g},${b})`;
  }
}

export function AlignmentHeatmap() {
  const [data, setData] = useState<AlignmentData | null>(null);
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    text: string;
  } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch("/api/alignment")
      .then((r) => r.json())
      .then(setData);
  }, []);

  if (!data) {
    return (
      <div className="flex items-center justify-center h-96 text-gray-400">
        Loading alignment data...
      </div>
    );
  }

  const { names, matrix, sharedCounts } = data;
  const n = names.length;
  const cellSize = 16;
  const labelWidth = 160;
  const topPadding = 40; // extra space for rotated column labels
  const svgWidth = labelWidth + n * cellSize + 10;
  const svgHeight = labelWidth + topPadding + n * cellSize;

  return (
    <div ref={containerRef} className="relative overflow-x-auto">
      <svg
        width={svgWidth}
        height={svgHeight}
        className="font-sans"
      >
        {/* Row labels (left) */}
        {names.map((name, i) => (
          <text
            key={`row-${i}`}
            x={labelWidth - 4}
            y={labelWidth + topPadding + i * cellSize + cellSize / 2 + 4}
            textAnchor="end"
            fontSize={9}
            fill="#666"
          >
            {name}
          </text>
        ))}

        {/* Column labels (top, rotated) */}
        {names.map((name, j) => (
          <text
            key={`col-${j}`}
            x={0}
            y={0}
            textAnchor="start"
            fontSize={9}
            fill="#666"
            transform={`translate(${labelWidth + j * cellSize + cellSize / 2 + 3}, ${labelWidth + topPadding - 4}) rotate(-60)`}
          >
            {name}
          </text>
        ))}

        {/* Heatmap cells */}
        {matrix.map((row, i) =>
          row.map((value, j) => {
            if (i === j) return null;
            return (
              <rect
                key={`${i}-${j}`}
                x={labelWidth + j * cellSize}
                y={labelWidth + topPadding + i * cellSize}
                width={cellSize}
                height={cellSize}
                fill={getColor(value)}
                stroke="white"
                strokeWidth={0.5}
                onMouseEnter={(e) => {
                  const rect =
                    containerRef.current?.getBoundingClientRect();
                  if (rect) {
                    setTooltip({
                      x:
                        e.clientX -
                        rect.left +
                        (containerRef.current?.scrollLeft || 0),
                      y: e.clientY - rect.top,
                      text: `${names[i]} & ${names[j]}: ${(value * 100).toFixed(1)}% agreement (${sharedCounts[i][j]} shared votes)`,
                    });
                  }
                }}
                onMouseLeave={() => setTooltip(null)}
                className="cursor-pointer"
              />
            );
          })
        )}

        {/* Diagonal */}
        {names.map((_, i) => (
          <rect
            key={`diag-${i}`}
            x={labelWidth + i * cellSize}
            y={labelWidth + i * cellSize}
            width={cellSize}
            height={cellSize}
            fill="#e5e7eb"
            stroke="white"
            strokeWidth={0.5}
          />
        ))}
      </svg>

      {/* Tooltip */}
      {tooltip && (() => {
        const containerWidth = containerRef.current?.offsetWidth || 800;
        const flippedX = tooltip.x > containerWidth - 300;
        return (
          <div
            className="absolute bg-gray-900 text-white text-xs px-3 py-2 rounded shadow-lg pointer-events-none z-50 whitespace-nowrap"
            style={{
              left: flippedX ? undefined : tooltip.x + 10,
              right: flippedX ? (containerWidth - tooltip.x + 10) : undefined,
              top: tooltip.y - 30,
            }}
          >
            {tooltip.text}
          </div>
        );
      })()}

      {/* Legend */}
      <div className="flex items-center gap-4 mt-6 text-sm text-gray-500">
        <span>Less aligned</span>
        <div className="flex h-4">
          {Array.from({ length: 20 }, (_, i) => (
            <div
              key={i}
              className="w-3 h-4"
              style={{ backgroundColor: getColor(0.85 + (i / 20) * 0.15) }}
            />
          ))}
        </div>
        <span>More aligned</span>
      </div>
    </div>
  );
}
