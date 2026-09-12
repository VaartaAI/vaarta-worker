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

## Clustering

Articles about the same event are grouped into a cluster; the LLM summarises
the cluster, not individual articles. Matching runs in two stages:

1. **Semantic** (default). Each new article gets a 384-dim `gemini-embedding-001`
   vector of `title. <first 200 chars of body>` and is compared by cosine
   similarity (pgvector `<=>`) against embedded articles in clusters from the
   last `CLUSTER_LOOKBACK_HOURS`. It joins the nearest cluster when
   `cosine >= CLUSTER_EMBEDDING_THRESHOLD` (0.85), or when
   `cosine >= CLUSTER_HYBRID_EMBEDDING_THRESHOLD` (0.80) **and** the two titles'
   trigram similarity `>= CLUSTER_HYBRID_TRIGRAM_THRESHOLD` (0.35).
2. **Trigram** (fallback). pg_trgm `similarity(title, title) > CLUSTER_THRESHOLD`
   (0.42). Used when the article has no embedding — API down, quota hit,
   `CLUSTERING_USE_EMBEDDINGS=false` — or when no embedded neighbour exists yet.

Embeddings are fetched once per feed per run (batched, 40 texts per call), so
ingest never makes per-article embedding requests. Gemini free-tier quota for
`gemini-embedding-001`, separate from the summarization model's bucket:

| Quota | Limit | Notes |
|---|---|---|
| per minute | 100 texts | every text in a batch counts; rejected batches count too |
| per day | **1000 texts** | quotaId `EmbedContentRequestsPerDay…-FreeTier`; resets midnight Pacific (07:00 UTC / 12:30 IST) |

Steady state (~400–500 new articles/day) fits. Bulk backfills and repeated test
runs do not — that is how the cap was found. Client behaviour:

- per-minute 429 → wait a full 61 s window (the server's shorter `retryDelay`
  collides with the rejected batch), retry up to 3× within
  `EMBEDDING_MAX_WAIT_SECONDS`, else that feed falls back to trigram;
- per-day 429 → raise `EmbeddingQuotaExhausted` immediately, no retries; ingest
  logs `embeddings_disabled_for_run` once and clusters the rest of the run by
  trigram. Those articles get `embedding = NULL` and are simply invisible to
  the vector search later;
- network blips / 5xx → 3 s, 6 s, 9 s retries.

After enabling embeddings on an existing database, or after an outage, fill the
gaps so recent articles have neighbours:

```bash
BACKFILL_HOURS=72 python main.py backfill-embeddings
```

Calibration (2026-09-12, 368 real articles, nearest-neighbour pairs): every
pair at cosine >= 0.85 was the same event or the same running story; the
closest unrelated pair scored 0.849, so do not lower that threshold. In the
0.80–0.85 band, a trigram floor of 0.25 admitted five pairs and all five were
false merges (e.g. a 1986 rail crash vs today's live blog); 0.35 admitted none.
`cluster_joined` log lines carry `method`, `cosine` and `trigram` for every
join — grep them periodically and re-tune if you see bad merges.


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
python main.py backfill-embeddings  # embed recent rows missing a vector (one-off / after outage)
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
│   ├── trend.py               # one-shot: rescore clusters
│   └── backfill_embeddings.py # one-shot: embed rows with embedding IS NULL
├── services/
│   ├── sources/               # NewsSource subclasses + registry
│   ├── clustering_service.py  # embedding + trigram clustering (category-blind)
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
│   ├── embeddings/            # EmbeddingClient interface + Gemini (paced to free-tier quota)
│   ├── queue/                 # Queue interface + Postgres FIFO with SKIP LOCKED
│   └── budget/                # TokenBudget interface + in-memory & Redis impls
├── models/                    # plain dataclasses
└── migrations/
    └── 001_summarization_queue.sql
```
