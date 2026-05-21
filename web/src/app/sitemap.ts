import type { MetadataRoute } from "next";
import { unstable_noStore as noStore } from "next/cache";
import { sql } from "@/lib/db";
import { slugify } from "@/lib/slugify";

// Always reflect current candidate state: when a candidate opts out via the
// review page we need them gone from the sitemap immediately, not on the next
// build. force-dynamic + noStore together opt out of both the route cache and
// the underlying fetch/data cache (neon serverless queries hit fetch).
export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  noStore();
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: "https://jerseyvotes.org", priority: 1.0, changeFrequency: "daily" },
    { url: "https://jerseyvotes.org/candidates", priority: 1.0, changeFrequency: "daily" },
    { url: "https://jerseyvotes.org/candidates/quiz", priority: 1.0, changeFrequency: "weekly" },
    { url: "https://jerseyvotes.org/candidates/methodology", priority: 0.9, changeFrequency: "monthly" },
    { url: "https://jerseyvotes.org/members", priority: 0.8, changeFrequency: "weekly" },
    { url: "https://jerseyvotes.org/votes", priority: 0.8, changeFrequency: "daily" },
    { url: "https://jerseyvotes.org/divisive", priority: 0.7, changeFrequency: "weekly" },
    { url: "https://jerseyvotes.org/alignment", priority: 0.6, changeFrequency: "weekly" },
    { url: "https://jerseyvotes.org/blocs", priority: 0.6, changeFrequency: "weekly" },
    { url: "https://jerseyvotes.org/quiz", priority: 0.7, changeFrequency: "weekly" },
    { url: "https://jerseyvotes.org/about", priority: 0.5, changeFrequency: "monthly" },
  ];

  const [members, candidates] = await Promise.all([
    sql`SELECT canonical_name FROM members ORDER BY canonical_name`,
    sql`SELECT vote_je_slug FROM candidates WHERE election_year = 2026 AND opted_out_at IS NULL ORDER BY vote_je_slug`,
  ]);

  const memberRoutes: MetadataRoute.Sitemap = members.map(
    (m: Record<string, unknown>) => ({
      url: `https://jerseyvotes.org/members/${slugify(m.canonical_name as string)}`,
      priority: 0.7,
      changeFrequency: "weekly" as const,
    })
  );

  const candidateRoutes: MetadataRoute.Sitemap = candidates.map(
    (c: Record<string, unknown>) => ({
      url: `https://jerseyvotes.org/candidates/${c.vote_je_slug as string}`,
      priority: 0.9,
      changeFrequency: "daily" as const,
    })
  );

  return [...staticRoutes, ...candidateRoutes, ...memberRoutes];
}
