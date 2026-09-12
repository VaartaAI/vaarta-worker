"""
Backfill worker — one-shot.

Embeds recent articles that have embedding = NULL (ingested before migration
005, or while the embedding API was down) so semantic clustering has
neighbours to match against. Safe to re-run; idempotent.

    BACKFILL_HOURS=72 python main.py backfill-embeddings
"""
from __future__ import annotations
import os
import time

from dotenv import load_dotenv
load_dotenv()

from infra.logging_config import configure_logging  # noqa: E402
configure_logging(level=os.getenv("LOG_LEVEL", "INFO"))

from infra.observability import configure_observability  # noqa: E402
configure_observability(service_name="vaarta-backfill-embeddings")

import structlog  # noqa: E402

from config.settings import Settings  # noqa: E402
from db.connection import DatabasePool  # noqa: E402
from db.repositories.article_repository import ArticleRepository  # noqa: E402
from infra.embeddings import EmbeddingError, build_embedder, embedding_text  # noqa: E402
from models.article import Article  # noqa: E402
from models.source import Source  # noqa: E402

logger = structlog.get_logger(__name__)

BATCH = 100
MAX_CONSECUTIVE_FAILURES = 3
FAILURE_PAUSE_SECONDS = 30


def run() -> None:
    settings = Settings.from_env()
    log = logger.bind(worker="backfill_embeddings")
    hours = int(os.getenv("BACKFILL_HOURS", str(settings.cluster_lookback_hours + 24)))

    embedder = build_embedder(settings)
    if embedder is None:
        log.error("embeddings_disabled", hint="set GEMINI_API_KEY and CLUSTERING_USE_EMBEDDINGS=true")
        return

    pool = DatabasePool(settings)
    repo = ArticleRepository(pool)
    placeholder = Source(name="", domain="")
    total = 0
    failures = 0
    try:
        while True:
            rows = repo.missing_embedding(since_hours=hours, limit=BATCH)
            if not rows:
                break
            texts = [
                embedding_text(Article(url="", title=r["title"], body_text=r["body_text"] or "", source=placeholder),
                               settings.embedding_body_chars)
                for r in rows
            ]
            try:
                vectors = embedder.embed(texts)
            except EmbeddingError as exc:
                failures += 1
                log.warning("batch_failed", attempt=failures, error=str(exc)[:200])
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    log.error("backfill_aborted", embedded=total, remaining=len(rows))
                    return
                time.sleep(FAILURE_PAUSE_SECONDS)
                continue
            failures = 0
            updated = repo.set_embeddings([(r["id"], v) for r, v in zip(rows, vectors)])
            total += updated
            log.info("batch_embedded", rows=len(rows), updated=updated, total=total)
            if updated == 0:
                log.error("no_rows_updated_aborting")
                break
        log.info("backfill_complete", embedded=total, window_hours=hours)
    finally:
        pool.close_all()


if __name__ == "__main__":
    run()
