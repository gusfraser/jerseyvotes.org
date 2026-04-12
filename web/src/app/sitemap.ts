import type { MetadataRoute } from "next";
import { sql } from "@/lib/db";
import { slugify } from "@/lib/slugify";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: "https://jerseyvotes.org", priority: 1.0, changeFrequency: "daily" },
    { url: "https://jerseyvotes.org/members", priority: 0.9, changeFrequency: "weekly" },
    { url: "https://jerseyvotes.org/votes", priority: 0.9, changeFrequency: "daily" },
    { url: "https://jerseyvotes.org/divisive", priority: 0.8, changeFrequency: "weekly" },
    { url: "https://jerseyvotes.org/alignment", priority: 0.7, changeFrequency: "weekly" },
    { url: "https://jerseyvotes.org/blocs", priority: 0.7, changeFrequency: "weekly" },
    { url: "https://jerseyvotes.org/quiz", priority: 0.8, changeFrequency: "weekly" },
    { url: "https://jerseyvotes.org/about", priority: 0.5, changeFrequency: "monthly" },
  ];

  const members = await sql`SELECT canonical_name FROM members ORDER BY canonical_name`;
  const memberRoutes: MetadataRoute.Sitemap = members.map(
    (m: Record<string, unknown>) => ({
      url: `https://jerseyvotes.org/members/${slugify(m.canonical_name as string)}`,
      priority: 0.8,
      changeFrequency: "weekly" as const,
    })
  );

  return [...staticRoutes, ...memberRoutes];
}
