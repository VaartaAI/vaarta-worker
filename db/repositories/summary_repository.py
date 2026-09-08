from __future__ import annotations
import json
import logging
from psycopg2 import DatabaseError, InterfaceError, OperationalError
from psycopg2.extras import RealDictCursor

from models.summary import Summary
from db.repositories.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class SummaryRepository(BaseRepository):

    def save(self, summary: Summary) -> Summary:
        """
        Persist a summary AND propagate its category to the parent cluster
        in a single transaction. Both writes succeed together or neither does,
        so we never end up with a saved summary and a NULL cluster category.
        """
        conn = self._pool.get_connection()
        broken = False
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO summaries
                      (cluster_id, summary_text, why_it_matters, deep_explainer,
                       category, entities, topics, is_safe, sources_agree)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (cluster_id) DO UPDATE SET
                        summary_text   = EXCLUDED.summary_text,
                        why_it_matters = EXCLUDED.why_it_matters,
                        deep_explainer = EXCLUDED.deep_explainer,
                        category       = EXCLUDED.category,
                        entities       = EXCLUDED.entities,
                        topics         = EXCLUDED.topics
                    RETURNING id
                    """,
                    (
                        summary.cluster_id,
                        summary.summary_text,
                        summary.why_it_matters,
                        summary.deep_explainer,
                        summary.category,
                        json.dumps(summary.entities),
                        json.dumps(summary.topics),
                        summary.is_safe,
                        summary.sources_agree,
                    ),
                )
                row = cur.fetchone()

                cur.execute(
                    """
                    UPDATE article_clusters
                    SET category = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (summary.category, summary.cluster_id),
                )

            conn.commit()
            summary.id = row["id"]
            return summary
        except DatabaseError as exc:
            try:
                conn.rollback()
            except (OperationalError, InterfaceError):
                broken = True
            logger.error("save_summary_failed cluster=%d error=%s", summary.cluster_id, exc)
            raise
        finally:
            self._pool.release_connection(conn, broken=broken)

    def exists_for_cluster(self, cluster_id: int) -> bool:
        row = self._execute_one(
            "SELECT 1 FROM summaries WHERE cluster_id = %s",
            (cluster_id,),
        )
        return row is not None
