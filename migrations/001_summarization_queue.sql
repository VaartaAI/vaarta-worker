-- Queue between ingestion and LLM workers.
-- Ingestion enqueues new cluster ids; LLM workers claim them with
-- FOR UPDATE SKIP LOCKED so multiple workers can run concurrently.

CREATE TABLE IF NOT EXISTS summarization_queue (
    cluster_id   INTEGER     PRIMARY KEY REFERENCES article_clusters(id) ON DELETE CASCADE,
    status       TEXT        NOT NULL DEFAULT 'pending',
    enqueued_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_at    TIMESTAMPTZ,
    attempts     INTEGER     NOT NULL DEFAULT 0,
    last_error   TEXT
);

CREATE INDEX IF NOT EXISTS idx_queue_pending
    ON summarization_queue (enqueued_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_queue_in_progress
    ON summarization_queue (locked_at)
    WHERE status = 'in_progress';

-- Cluster category is now written by the LLM worker after summarization.
-- Brand-new clusters live with NULL category until their first summary lands.
ALTER TABLE article_clusters ALTER COLUMN category DROP NOT NULL;
