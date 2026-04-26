# vaarta-worker

News ingestion and summarization pipeline for VaartaAI. Fetches headlines from NewsAPI, clusters related articles, and generates AI summaries using Groq (LLaMA 3.3-70B).

## How it works

1. **Fetch** — pulls today's top Indian news headlines from NewsAPI
2. **Cluster** — groups related articles using sentence similarity (threshold: 0.35)
3. **Summarize** — calls Groq to generate a structured summary for each cluster:
   - Headline, summary, why it matters, background context
   - Topics, entities, source trust scores
4. **Store** — writes everything to Neon PostgreSQL

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in your credentials in .env
```

## Running

```bash
# Run the full pipeline
python3 main.py

# Summarize any clusters that failed (e.g. after hitting token limits)
python3 scripts/summarize_pending.py
```

## Environment variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | Neon PostgreSQL connection string |
| `NEWSAPI_KEY` | NewsAPI.org API key |
| `GROQ_API_KEY` | Groq API key (free tier: 100k tokens/day) |

## Project structure

```
vaarta-worker/
├── main.py                  # Entry point
├── config/
│   └── settings.py          # Pydantic settings
├── models/
│   ├── article.py           # Article dataclass
│   └── summary.py           # Summary dataclass
├── db/
│   ├── connection.py        # Connection pool
│   └── repositories/        # Data access layer
├── pipeline/
│   └── ingestion_pipeline.py  # Orchestrates fetch → cluster → summarize → store
├── services/
│   ├── clustering_service.py
│   ├── summarization_service.py
│   └── fetchers/
│       └── newsapi_fetcher.py
└── scripts/                 # One-off utility scripts
    ├── summarize_pending.py
    ├── backfill_background.py
    └── check_schema.py
```
