import type { MetadataRoute } from "next";
import { sql } from "@/lib/db";
import { slugify } from "@/lib/slugify";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
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
    sql`SELECT vote_je_slug FROM candidates WHERE election_year = 2026 ORDER BY vote_je_slug`,
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
