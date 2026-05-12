# Jersey Votes

A civic transparency platform for the Jersey States Assembly. Find candidates whose priorities match yours, explore 22 years of voting data, and see how politicians actually voted.

**[jerseyvotes.org](https://jerseyvotes.org)**

The 2026 general election is on **7 June 2026**. The current focus is the new Candidates section — manifestos for all 92 candidates classified against a 16-topic taxonomy, with a quiz that ranks them against your own priorities. Every score is transparent and traceable to a verbatim manifesto quote.

## Features

### Election-focused (live now)

- **Candidates index** — Browse all 92 candidates for the 2026 election, filter by constituency, role (Deputy / Connétable / Senator), party, or topic addressed
- **Candidate profile pages** — Per-candidate manifesto, extracted topics with salience bars, stance grid (agree / disagree / neutral / not-addressed), and source quotes for every claim
- **"Find your candidate" quiz** — Rank your 5 priority topics, answer ~40 canonical policy statements, get candidates ranked by priority-weighted topic overlap + stance alignment. See `/candidates/quiz`
- **Methodology page** — The full scoring formula, LLM prompts, taxonomy, limitations, and candidate-correction process published openly. See `/candidates/methodology`

### Voting-record analysis (year-round)

- **Member profiles** — Voting record, participation rate, and per-topic analysis for all 49 active members (and 109 former members back to 2004)
- **Vote explorer** — Browse 5,423 recorded votes, filterable by 16 topic categories and legislative stage
- **Alignment matrix** — Interactive heatmap of pairwise voting agreement between all active members
- **Voting blocs** — PCA-based political positioning scatter plot with clustering, filterable by topic
- **Voting quiz** — Answer questions on real divisive votes and get matched to your most aligned sitting members
- **Share results** — Dynamic OG images for social-media sharing of quiz results

## Data sources

- **Candidate profiles** scraped from [vote.je](https://www.vote.je/candidates), the official States Greffe election site
- **Voting records** sourced from [States Assembly of Jersey](https://statesassembly.je/votes)

Dataset:

| Source | Count |
|---|---|
| Candidates (2026 election) | 92 |
| Members (active) | 49 |
| Members (since 2004) | 158 |
| Propositions | 2,261 |
| Recorded divisions | 5,423 |
| Individual votes | 275,000+ |
| Canonical policy statements (quiz) | 38 |
| Topic categories | 16 |

## Scoring methodology (candidates)

The candidate quiz scores each candidate against your inputs as:

```
Match(c) = 0.4 × T(c) + 0.6 × S(c)
```

Where:

- **T** = priority-weighted topic overlap (how much of their manifesto goes to topics you ranked)
- **S** = stance alignment (where you both took a position, do you agree?)
- **C** = coverage (separately reported, not blended) — flags low-confidence matches when the candidate didn't address most of your priorities

Every stance attribution is checked against the manifesto with a verbatim substring match — if the LLM-supplied quote doesn't appear in the text exactly, the stance is rejected and demoted to `not_addressed`. This is the primary guard against model hallucination.

Full details at [/candidates/methodology](https://jerseyvotes.org/candidates/methodology).

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router, TypeScript) |
| Styling | Tailwind CSS v4 |
| Database | Neon PostgreSQL (`@neondatabase/serverless`) |
| Data pipeline | Python 3.11 (pandas, psycopg2, httpx, pyyaml) |
| LLM (candidate classification) | Claude Sonnet 4.5 via `anthropic` SDK |
| LLM (proposition classification) | Claude Haiku 4.5 (cheaper, well-calibrated for short titles) |
| Scraping | Python httpx (vote.je), urllib (statesassembly.je) |
| Visualisations | SVG (custom heatmap, PCA scatter plot) |

## Project structure

```
pipeline/                           # Python data pipeline
  schema.sql                        # Fresh-rebuild schema
  migrations/                       # Additive migrations
    001_candidates.sql              # Candidates feature tables (idempotent)
  canonical_questions.yaml          # 38 agree/disagree statements, 16 topics
  incumbent_overrides.csv           # Manual candidate→member nickname mappings

  # Voting-record pipeline (year-round)
  ingest.py                         # CSV → normalised PostgreSQL tables
  scrape.py                         # Scrape proposition pages from statesassembly.je
  classify.py                       # Keyword + Haiku topic classification
  classify_ollama.py                # Local-LLM alternative (offline)
  extend_summaries.py               # Extended voter-friendly summaries
  summarize_priority.py             # Priority-ordered summarisation
  analyse.py                        # Voting alignment, blocs, PCA

  # Candidates pipeline (election-focused)
  scrape_candidates.py              # Fetch vote.je profiles → DB
  find_enhanced_manifestos.py       # Web-search for fuller manifestos (Claude web_search)
  link_incumbents.py                # Match candidates to sitting members
  classify_candidates.py            # Sonnet topic + stance extraction
  generate_correction_previews.py   # Per-candidate outreach CSV

web/                                # Next.js app
  src/app/
    page.tsx                        # Homepage with election countdown
    candidates/                     # Candidates section
      page.tsx                      # Filterable index
      [slug]/                       # Per-candidate profile
      quiz/                         # Find-your-candidate quiz
      methodology/                  # Public scoring methodology
      correction/[token]/           # Private candidate-correction preview
    members/                        # Sitting member profiles
    votes/                          # Vote explorer
    alignment/                      # Pairwise alignment heatmap
    blocs/                          # PCA scatter plot
    quiz/                           # Voting-record quiz
    api/                            # API routes (candidates/quiz, share image, etc.)
```

## Getting started

### Prerequisites

- Node.js 20+
- Python 3.11+
- A Neon PostgreSQL database
- Anthropic API key (for candidate classification — `ANTHROPIC_API_KEY`)

### Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/gusfraser/jerseyvotes.org.git
   cd jerseyvotes.org
   ```

2. Create a `.env` file at the repo root for the Python pipeline:
   ```
   DATABASE_URL=postgresql://user:password@host/neondb?sslmode=require
   ANTHROPIC_API_KEY=sk-ant-...
   ```

   Plus `web/.env.local` for the Next.js app (same `DATABASE_URL`):
   ```
   DATABASE_URL=postgresql://user:password@host/neondb?sslmode=require
   ```

3. Create the Python venv and install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. Initialise the database schema. **`schema.sql` drops tables — only use on an empty DB.** For an existing DB, apply additive migrations only:
   ```bash
   # Fresh DB
   psql "$DATABASE_URL" -f pipeline/schema.sql

   # OR additive (idempotent) — safe on a populated DB
   psql "$DATABASE_URL" -f pipeline/migrations/001_candidates.sql
   ```

5. Run the voting-record pipeline (one-time bootstrap):
   ```bash
   python pipeline/ingest.py        # Load CSV data
   python pipeline/scrape.py        # Scrape proposition pages
   python pipeline/classify.py      # Topic classification (Haiku)
   ```

6. Run the candidates pipeline (once per election cycle, or to refresh):
   ```bash
   python pipeline/scrape_candidates.py        # ~30s, no API cost
   python pipeline/find_enhanced_manifestos.py # Optional: web-search for fuller manifestos
   python pipeline/link_incumbents.py \
     --overrides pipeline/incumbent_overrides.csv
   python pipeline/classify_candidates.py      # ~60-90 min, ~$3.50 in Sonnet API
   python pipeline/generate_correction_previews.py \
     --host https://jerseyvotes.org > corrections.csv
   ```

   `find_enhanced_manifestos.py` uses the Claude `web_search` server-side tool
   to look up `"{candidate}" manifesto Jersey election 2026`, picks the
   candidate-owned source (personal site, party page, public Facebook post),
   and stores the verbatim text in `candidates.enhanced_manifesto_*`.
   `classify_candidates.py` then prefers that text over the vote.je scrape;
   the original `manifesto_text` is preserved untouched.

7. Run the web app:
   ```bash
   cd web
   npm install
   npm run dev
   ```

8. Open [http://localhost:3000](http://localhost:3000).

### Common gotchas

- **`DATABASE_URL` shadowed by your shell**: if your interactive shell exports a different `DATABASE_URL` (e.g. for another project), Next.js will use that rather than `web/.env.local`. Symptom: `getaddrinfo ENOTFOUND <some-other-host>`. Fix: `unset DATABASE_URL` before `npm run dev`, or rename the env var in this project.
- **`ANTHROPIC_API_KEY=""` shadow**: same issue, different var. The pipeline already calls `load_dotenv(override=True)` to defeat this.
- **Neon connection drops mid-batch**: long Sonnet calls (~30-50s) can outlast Neon's idle connection. `classify_candidates.py` uses TCP keepalives + reconnect-on-error to recover automatically.

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change. Issues, redlines on the methodology, and questions about specific candidate classifications are all useful.

## Licence

[MIT](LICENSE)

## Author

Built by [Gus Fraser](https://github.com/gusfraser), a Jersey resident.
