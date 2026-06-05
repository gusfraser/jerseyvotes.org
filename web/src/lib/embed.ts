// Query-time embedding via the Voyage REST API (no SDK dependency — one fetch).
// MUST use the same model as pipeline/build_rag_index.py so query and document
// vectors live in the same space (and match the vector(1024) column).

const VOYAGE_URL = "https://api.voyageai.com/v1/embeddings";
export const VOYAGE_MODEL = process.env.VOYAGE_MODEL || "voyage-3.5-lite";

export async function embedQuery(text: string): Promise<number[]> {
  const key = process.env.VOYAGE_API_KEY;
  if (!key) throw new Error("VOYAGE_API_KEY not set");

  const res = await fetch(VOYAGE_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${key}`,
    },
    body: JSON.stringify({
      input: [text],
      model: VOYAGE_MODEL,
      input_type: "query",
    }),
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Voyage embeddings ${res.status}: ${body.slice(0, 300)}`);
  }

  const json = (await res.json()) as { data: { embedding: number[] }[] };
  const vec = json?.data?.[0]?.embedding;
  if (!Array.isArray(vec)) throw new Error("Voyage response missing embedding");
  return vec;
}

// pgvector accepts a bracketed string literal cast to ::vector.
export function toVectorLiteral(vec: number[]): string {
  return "[" + vec.join(",") + "]";
}
