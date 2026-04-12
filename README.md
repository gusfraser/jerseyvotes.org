# Jersey Votes

A civic transparency platform for the Jersey States Assembly. Explore 22 years of voting data, discover how politicians vote, and find representatives aligned with your views.

**[jerseyvotes.org](https://jerseyvotes.org)**

## Features

- **Member Profiles** - Voting record, participation rates, and per-topic analysis for all 49 active members (and 109 former members back to 2004)
- **Vote Explorer** - Browse 5,423 recorded votes, filterable by 16 topic categories and legislative stage
- **Alignment Matrix** - Interactive heatmap showing pairwise voting agreement between all active members
- **Voting Blocs** - PCA-based political positioning scatter plot with clustering, filterable by topic
- **Voter Alignment Quiz** - Answer 30 questions on real divisive votes and get matched to your most aligned politicians
- **Share Results** - Dynamic OG images for social media sharing of quiz results

## Data

All voting data is sourced from the [States Assembly of Jersey](https://statesassembly.je/votes). The dataset covers:

- **275,000** individual votes
- **158** members (49 currently active)
- **2,261** propositions
- **5,423** recorded divisions
- **2004 - 2026** date range

Propositions are classified into 16 topic categories and linked to their source pages on statesassembly.je.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router, TypeScript) |
| Styling | Tailwind CSS |
| Database | Neon PostgreSQL |
| Data Pipeline | Python (pandas, scikit-learn, scipy) |
| Topic Classification | Keyword pre-classifier + Ollama (local LLM) |
| Proposition Scraping | Python urllib |
| Visualisations | SVG (custom heatmap, PCA scatter plot) |

## Project Structure

```
pipeline/          # Python data pipeline
  ingest.py        # CSV to normalised PostgreSQL tables
  scrape.py        # Scrape proposition pages from statesassembly.je
  classify.py      # Keyword-based topic classification
  classify_ollama.py  # LLM topic classification + summaries
  extend_summaries.py # Extended voter-friendly summaries
  analyse.py       # Voting alignment, blocs, PCA analysis
  schema.sql       # Database schema

web/               # Next.js web application
  src/app/         # App Router pages
    members/       # Member list and profiles
    votes/         # Vote explorer and detail pages
    alignment/     # Pairwise alignment heatmap
    blocs/         # PCA scatter plot with clustering
    quiz/          # Voter alignment quiz
    about/         # About page
    api/           # API routes (alignment, blocs, quiz, share image)
```

## Getting Started

### Prerequisites

- Node.js 20+
- Python 3.11+
- A Neon PostgreSQL database
- Ollama (for topic classification and summaries)

### Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/gusfraser/jerseyvotes.org.git
   cd jerseyvotes.org
   ```

2. Set up the database. Create a `.env` file:
   ```
   DATABASE_URL=postgresql://user:password@host/neondb?sslmode=require
   ```

3. Run the data pipeline:
   ```bash
   pip install -r requirements.txt
   python pipeline/ingest.py      # Load CSV data
   python pipeline/scrape.py      # Scrape proposition pages
   python pipeline/classify.py    # Keyword classification
   python pipeline/classify_ollama.py --classify-only  # LLM classification
   ```

4. Set up the web app:
   ```bash
   cd web
   npm install
   cp ../.env .env.local
   npm run dev
   ```

5. Open [http://localhost:3000](http://localhost:3000)

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change.

## License

[MIT](LICENSE)

## Author

Built by [Gus Fraser](https://github.com/gusfraser), a Jersey resident.
