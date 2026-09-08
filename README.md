# vaarta-worker

News ingestion and summarization pipeline for Vaarta. Three independent workers connected by a Postgres-backed queue.

## How it works

```
┌──────────────────────┐                         ┌──────────────────────────────┐
│  ingest worker       │                         │  llm worker                  │
│  (cron, one-shot)    │   Postgres queue        │  (long-running daemon)       │
│                      │  ┌────────────────────┐ │                              │
│  fetch sources ─►    │  │ summarization_     │ │  claim cluster_id ──────────►│
│  dedup, cluster,     ├─►│   queue            ├─┤  call Groq                   │
│  save article        │  │ (FOR UPDATE SKIP   │ │  save Summary + cluster      │
│  enqueue cluster_id  │  │  LOCKED)           │ │    .category in 1 tx         │
└──────────────────────┘  └────────────────────┘ │  ack queue row               │
                                                 └──────────────────────────────┘

┌──────────────────────┐
│  trend worker        │   reads cluster.article_count and cluster.category
│  (cron, one-shot)    │   (now LLM-authoritative) and writes importance_score
└──────────────────────┘
```

Sources are configured in `config/sources.yaml`. All sources are RSS feeds.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in DATABASE_URL and GROQ_API_KEY and/or GEMINI_API_KEY
```

Apply pending migrations:

```bash
python main.py migrate
```

This applies every unapplied `*.sql` file in `migrations/` in lexicographic order and tracks them in a `schema_migrations` table, so re-running is a no-op.

## Running

```bash
python main.py migrate  # apply pending SQL migrations
python main.py ingest   # fetch from sources, cluster, enqueue
python main.py llm      # consume queue, summarize (run continuously)
python main.py trend    # recompute importance scores
```

Typical deployment:

```cron
*/15 * * * *  cd /path/to/vaarta-worker && python main.py ingest
*/30 * * * *  cd /path/to/vaarta-worker && python main.py trend
```

…and run `python main.py llm` as a long-running process (systemd unit, supervisor, K8s deployment, etc.). You can run **multiple llm workers** safely — the queue uses `FOR UPDATE SKIP LOCKED`.

## Adding a new source

Edit `config/sources.yaml`:

```yaml
- type: rss
  name: "My Source"
  url: https://example.com/feed.xml
  trust_score: 4
```

No code change required. New `type`s (e.g. GNews) need a new class in `services/sources/` plus one branch in `registry.py`.

## LLM providers

The LLM worker uses a **fallback pool** of providers, tried in this order:

1. **Groq** (LLaMA 3.3-70B) — primary, fastest, ~100k tokens/day free.
2. **Gemini** (gemini-2.5-flash) — fallback, ~1M tokens/day free.

If Groq returns a daily-quota error or its in-memory budget is exhausted, the worker switches to Gemini for the rest of the day. Both providers have their own per-day budget tracked in memory.

You only need *one* of the keys to be set. With both, you get the full fallback. Add new providers by writing a class in `infra/llm/` that implements `LLMClient` and registering it in `workers/llm.py`.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | yes | Postgres connection string (Neon works) |
| `GROQ_API_KEY` | one of the LLM keys | Groq API key |
| `GEMINI_API_KEY` | one of the LLM keys | Google AI Studio key (Gemini fallback) |

See `.env.example` for tunables.

## Project structure

```
vaarta-worker/
├── main.py                    # dispatcher: routes to a worker
├── config/
│   ├── settings.py            # env-driven config
│   └── sources.yaml           # the source list
├── workers/
│   ├── ingest.py              # one-shot: fetch -> cluster -> enqueue
│   ├── llm.py                 # long-running: drain queue, summarize
│   └── trend.py               # one-shot: rescore clusters
├── services/
│   ├── sources/               # NewsSource subclasses + registry
│   ├── clustering_service.py  # title-similarity clustering (category-blind)
│   └── summarization_service.py
├── db/
│   ├── connection.py
│   └── repositories/
│       ├── article_repository.py
│       ├── cluster_repository.py
│       ├── source_repository.py
│       └── summary_repository.py    # save() is summary + cluster.category in 1 tx
├── infra/
│   ├── logging_config.py
│   ├── retry.py
│   ├── llm/                   # LLM provider interface + Groq/Gemini/Fallback
│   ├── queue/                 # Queue interface + Postgres FIFO with SKIP LOCKED
│   └── budget/                # TokenBudget interface + in-memory & Redis impls
├── models/                    # plain dataclasses
└── migrations/
    └── 001_summarization_queue.sql
```
