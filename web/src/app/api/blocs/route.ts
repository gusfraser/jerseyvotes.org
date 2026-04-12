import { NextResponse } from "next/server";
import { sql } from "@/lib/db";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const topicsParam = searchParams.get("topics"); // pipe-separated
  const topics = topicsParam ? topicsParam.split("|") : null;

  const members = await sql`
    SELECT member_id, canonical_name
    FROM members WHERE is_currently_active ORDER BY canonical_name
  `;

  // Fetch available topics for the filter
  // Count votes per topic (principles + third reading, current term)
  const allTopics = await sql`
    SELECT p.topic_primary, COUNT(DISTINCT vd.division_id) as vote_count
    FROM vote_divisions vd
    JOIN propositions p ON vd.proposition_id = p.proposition_id
    WHERE p.topic_primary IS NOT NULL
      AND vd.division_stage IN ('principles', 'third_reading')
      AND vd.date >= '2022-07-01'
    GROUP BY p.topic_primary
    ORDER BY p.topic_primary
  `;

  const votes = topics
    ? await sql`
        SELECT v.member_id, v.division_id, v.vote
        FROM votes v
        JOIN vote_divisions vd ON v.division_id = vd.division_id
        JOIN propositions p ON vd.proposition_id = p.proposition_id
        WHERE v.vote IN ('Pour', 'Contre')
          AND vd.division_stage IN ('principles', 'third_reading')
          AND vd.date >= '2022-07-01'
          AND v.member_id IN (SELECT member_id FROM members WHERE is_currently_active)
          AND p.topic_primary = ANY(${topics})
      `
    : await sql`
        SELECT v.member_id, v.division_id, v.vote
        FROM votes v
        JOIN vote_divisions vd ON v.division_id = vd.division_id
        WHERE v.vote IN ('Pour', 'Contre')
          AND vd.division_stage IN ('principles', 'third_reading')
          AND vd.date >= '2022-07-01'
          AND v.member_id IN (SELECT member_id FROM members WHERE is_currently_active)
      `;

  // Build vote vectors per member
  const allDivisions = new Set<number>();
  const memberVotes: Record<number, Record<number, number>> = {};

  for (const v of votes) {
    const mid = v.member_id as number;
    const did = v.division_id as number;
    allDivisions.add(did);
    if (!memberVotes[mid]) memberVotes[mid] = {};
    memberVotes[mid][did] = v.vote === "Pour" ? 1 : -1;
  }

  const divIds = Array.from(allDivisions).sort();
  const ids = members.map((m: Record<string, unknown>) => m.member_id as number);
  const names = members.map((m: Record<string, unknown>) => m.canonical_name as string);

  // Build matrix and do PCA (simple 2D projection via SVD-like approach)
  // For a proper PCA we'd use a library, but we can approximate with power iteration
  const n = ids.length;
  const d = divIds.length;

  // Create centered matrix
  const matrix: number[][] = ids.map((mid) => {
    return divIds.map((did) => memberVotes[mid]?.[did] ?? 0);
  });

  // Compute mean per dimension
  const means = new Array(d).fill(0);
  for (let j = 0; j < d; j++) {
    for (let i = 0; i < n; i++) {
      means[j] += matrix[i][j];
    }
    means[j] /= n;
  }

  // Center the matrix
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < d; j++) {
      matrix[i][j] -= means[j];
    }
  }

  // Compute covariance-like matrix (n x n) = M * M^T
  const cov: number[][] = Array.from({ length: n }, () => Array(n).fill(0));
  for (let i = 0; i < n; i++) {
    for (let j = i; j < n; j++) {
      let sum = 0;
      for (let k = 0; k < d; k++) {
        sum += matrix[i][k] * matrix[j][k];
      }
      cov[i][j] = sum / d;
      cov[j][i] = cov[i][j];
    }
  }

  // Power iteration for top 2 eigenvectors
  function powerIteration(
    mat: number[][],
    deflated?: number[]
  ): { vector: number[]; value: number } {
    const size = mat.length;
    let v = Array.from({ length: size }, () => Math.random() - 0.5);

    for (let iter = 0; iter < 100; iter++) {
      // Multiply
      const newV = new Array(size).fill(0);
      for (let i = 0; i < size; i++) {
        for (let j = 0; j < size; j++) {
          newV[i] += mat[i][j] * v[j];
        }
      }

      // Deflate if needed
      if (deflated) {
        const dot = newV.reduce((s, x, i) => s + x * deflated[i], 0);
        for (let i = 0; i < size; i++) {
          newV[i] -= dot * deflated[i];
        }
      }

      // Normalize
      const norm = Math.sqrt(newV.reduce((s, x) => s + x * x, 0));
      if (norm < 1e-10) break;
      v = newV.map((x) => x / norm);
    }

    const eigenvalue = v.reduce(
      (s, x, i) =>
        s + x * cov[i].reduce((ss, c, j) => ss + c * v[j], 0),
      0
    );

    return { vector: v, value: eigenvalue };
  }

  const pc1 = powerIteration(cov);
  const pc2 = powerIteration(cov, pc1.vector);

  // Project members onto PC1, PC2
  const coords = ids.map((_, i) => ({
    name: names[i],
    x: pc1.vector[i] * Math.sqrt(Math.abs(pc1.value)),
    y: pc2.vector[i] * Math.sqrt(Math.abs(pc2.value)),
  }));

  // Simple k-means clustering (k=5)
  const k = 5;
  // Initialize centroids from spread-out points
  const sorted = [...coords].sort((a, b) => a.x - b.x);
  let centroids = Array.from({ length: k }, (_, i) => {
    const idx = Math.floor((i / (k - 1)) * (sorted.length - 1));
    return { x: sorted[idx].x, y: sorted[idx].y };
  });

  let assignments = new Array(n).fill(0);

  for (let iter = 0; iter < 50; iter++) {
    // Assign to nearest centroid
    for (let i = 0; i < n; i++) {
      let minDist = Infinity;
      for (let c = 0; c < k; c++) {
        const dx = coords[i].x - centroids[c].x;
        const dy = coords[i].y - centroids[c].y;
        const dist = dx * dx + dy * dy;
        if (dist < minDist) {
          minDist = dist;
          assignments[i] = c;
        }
      }
    }

    // Recompute centroids
    const newCentroids = Array.from({ length: k }, () => ({
      x: 0,
      y: 0,
      count: 0,
    }));
    for (let i = 0; i < n; i++) {
      const c = assignments[i];
      newCentroids[c].x += coords[i].x;
      newCentroids[c].y += coords[i].y;
      newCentroids[c].count++;
    }
    centroids = newCentroids.map((c) => ({
      x: c.count > 0 ? c.x / c.count : 0,
      y: c.count > 0 ? c.y / c.count : 0,
    }));
  }

  const members_with_blocs = coords.map((c, i) => ({
    ...c,
    bloc: assignments[i],
  }));

  const topicList = allTopics.map((t: Record<string, unknown>) => ({
    name: t.topic_primary as string,
    count: Number(t.vote_count),
  }));
  const divisionCount = allDivisions.size;

  return NextResponse.json({
    members: members_with_blocs,
    topics: topicList,
    divisionCount,
  });
}
