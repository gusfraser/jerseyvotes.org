// Parish / constituency constants — side-effect-free so client components
// can import them without dragging in the DB driver (db.ts initialises
// neon() at module-load, which throws in the client bundle).

// Jersey's electoral structure for 2026:
//   Senator    — island-wide (constituency NULL); every voter can vote
//   Connétable — exactly one per parish (constituency == parish name)
//   Deputy     — by district; districts can:
//                  (a) match a parish 1:1 (St Brelade, St Clement, St Saviour),
//                  (b) split a parish (3 districts inside St Helier), or
//                  (c) combine parishes ("Grouville and St Martin", etc.).
//
// PARISH_DISTRICTS maps each parish to the list of `candidates.constituency`
// values relevant to a voter living in that parish — the parish itself (for
// the Connétable) plus any district covering that parish (for Deputies).
// Senators are always added on top by the filter logic, not by this map.
export const PARISHES = [
  "St Helier",
  "St Saviour",
  "St Brelade",
  "St Clement",
  "St Lawrence",
  "Trinity",
  "Grouville",
  "St Peter",
  "St Ouen",
  "St John",
  "St Martin",
  "St Mary",
] as const;
export type Parish = (typeof PARISHES)[number];

export const PARISH_DISTRICTS: Record<Parish, string[]> = {
  "St Helier": [
    "St Helier",
    "St Helier South",
    "St Helier Central",
    "St Helier North",
  ],
  "St Saviour": ["St Saviour"],
  "St Brelade": ["St Brelade"],
  "St Clement": ["St Clement"],
  "St Lawrence": ["St Lawrence", "St John, St Lawrence and Trinity"],
  "Trinity": ["Trinity", "St John, St Lawrence and Trinity"],
  "Grouville": ["Grouville", "Grouville and St Martin"],
  "St Peter": ["St Peter", "St Mary, St Ouen and St Peter"],
  "St Ouen": ["St Ouen", "St Mary, St Ouen and St Peter"],
  "St John": ["St John", "St John, St Lawrence and Trinity"],
  "St Martin": ["St Martin", "Grouville and St Martin"],
  "St Mary": ["St Mary", "St Mary, St Ouen and St Peter"],
};
