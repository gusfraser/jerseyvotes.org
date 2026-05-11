# Jersey Votes — Web App

The Next.js front-end for [jerseyvotes.org](https://jerseyvotes.org). See the [root README](../README.md) for the full project overview, data sources, and pipeline.

## Quick start

```bash
npm install
npm run dev
```

Opens on [http://localhost:3000](http://localhost:3000). The dev server uses Turbopack and live-reloads on save.

## Environment

Create `web/.env.local` with:

```
DATABASE_URL=postgresql://user:password@host/neondb?sslmode=require
```

The same `DATABASE_URL` is also used by the Python pipeline at the repo root. It points to a Neon PostgreSQL database — the schema is in [`pipeline/schema.sql`](../pipeline/schema.sql).

### Watch out for shell env shadowing

Next.js does NOT override `process.env` values set by your parent shell. If you have `DATABASE_URL` exported in your `~/.zshrc` (or similar) for another project, that wins over `.env.local`. Symptom: `getaddrinfo ENOTFOUND <some-other-host>` on page load. Fix:

```bash
unset DATABASE_URL
npm run dev
```

## Routes

| Path | Purpose |
|---|---|
| `/` | Election countdown + entry points to the quiz and candidates index |
| `/candidates` | Filterable candidate index (constituency, role, party, topic) |
| `/candidates/[slug]` | Per-candidate profile — manifesto, topic salience, stance grid, source quotes |
| `/candidates/quiz` | 3-step quiz: rank priorities → answer policy statements → see ranked matches |
| `/candidates/methodology` | Published scoring formula, prompts, limitations |
| `/candidates/correction/[token]` | Token-gated private preview for candidate corrections (`noindex`) |
| `/members` | Sitting Member list with vote counts |
| `/members/[slug]` | Per-member profile with full voting record |
| `/votes` | Paginated vote explorer |
| `/votes/[id]` | Vote breakdown |
| `/alignment` | Pairwise voting alignment heatmap |
| `/blocs` | PCA voting-bloc scatter |
| `/divisive` | Topic-level closeness metrics |
| `/quiz` | Voting-record quiz (matches you to a sitting Member) |
| `/about` | About page |
| `/api/candidates/quiz` | GET canonical questions, POST scoring |
| `/api/candidates/correction/[token]` | POST candidate correction notes |
| `/api/quiz` | Existing voting-record quiz API |

## Architecture

- **Server components by default**. Each page does `await sql\`...\`` directly against Neon serverless. No ORM — raw parameterised SQL via tagged template literals.
- **Client components** only where needed (the two quizzes, nav, charts). They live next to their server-component parent as `*-client.tsx`.
- **Database client** in [`src/lib/db.ts`](src/lib/db.ts) — exports `sql`, typed row shapes, the 16-topic taxonomy constant `TOPICS`, and `daysUntilElection()`.

## Styling

Tailwind CSS v4 via `@tailwindcss/postcss`. There is no `@tailwindcss/typography` plugin in this project — don't reach for `prose` classes (they'll silently do nothing). Style explicitly with utilities.

## Build

```bash
npm run build       # Production build (next build)
npm start           # Production server (next start)
npm run lint        # ESLint
```

Several pre-existing pages (e.g. `blocs/chart.tsx`, `nav.tsx`, `votes/page.tsx`) currently emit `react-hooks/set-state-in-effect` warnings. They predate the candidates work and don't block builds.
