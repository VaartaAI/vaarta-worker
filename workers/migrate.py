"""
Migration runner — applies any *.sql files in migrations/ that haven't run yet.

Tracks applied filenames in a `schema_migrations` table. Idempotent: running
it twice is a no-op. Files are applied in lexicographic order, which is why
they're prefixed with a zero-padded number.
"""
from __future__ import annotations
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from infra.logging_config import configure_logging  # noqa: E402
configure_logging(level=os.getenv("LOG_LEVEL", "INFO"))

from infra.observability import configure_observability  # noqa: E402
configure_observability(service_name="vaarta-migrate")

import psycopg2  # noqa: E402
import structlog  # noqa: E402

from config.settings import Settings  # noqa: E402

logger = structlog.get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def run() -> None:
    settings = Settings.from_env()
    log = logger.bind(worker="migrate")

    conn = psycopg2.connect(settings.database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename   TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.commit()

            cur.execute("SELECT filename FROM schema_migrations")
            applied = {row[0] for row in cur.fetchall()}

        files = sorted(p for p in MIGRATIONS_DIR.glob("*.sql"))
        if not files:
            log.warning("no_migrations_found", dir=str(MIGRATIONS_DIR))
            return

        for path in files:
            name = path.name
            if name in applied:
                log.info("skip_already_applied", file=name)
                continue

            sql = path.read_text(encoding="utf-8")
            log.info("applying", file=name)
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)",
                    (name,),
                )
            conn.commit()
            log.info("applied", file=name)

        log.info("migrate_complete")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run()
