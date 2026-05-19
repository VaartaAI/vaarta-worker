-- Per-source state for incremental fetching.
--
--   * last_fetched_at  — NewsAPI cursor: passed as the `from=` parameter so
--                        each call only returns articles published since
--                        the last successful fetch.
--   * last_etag /
--     last_modified    — RSS HTTP conditional GET: passed back to publishers
--                        so a 304 short-circuits parsing entirely.

CREATE TABLE IF NOT EXISTS source_state (
    source_key       TEXT        PRIMARY KEY,
    last_fetched_at  TIMESTAMPTZ,
    last_etag        TEXT,
    last_modified    TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
