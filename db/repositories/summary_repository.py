import json
from models.summary import Summary
from db.repositories.base_repository import BaseRepository


class SummaryRepository(BaseRepository):

    def save(self, summary: Summary) -> Summary:
        row = self._execute_one(
            """
            INSERT INTO summaries
              (cluster_id, summary_text, why_it_matters, deep_explainer, category, entities, topics, is_safe, sources_agree)
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
            )
        )
        summary.id = row["id"]
        return summary

    def exists_for_cluster(self, cluster_id: int) -> bool:
        row = self._execute_one(
            "SELECT 1 FROM summaries WHERE cluster_id = %s",
            (cluster_id,)
        )
        return row is not None
