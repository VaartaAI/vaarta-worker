from __future__ import annotations
import json
import logging

from models.article import Article
from models.summary import Summary
from db.repositories.article_repository import ArticleRepository
from config.settings import Settings
from infra.llm.base import LLMClient

logger = logging.getLogger(__name__)


class SummarizationService:
    """
    Builds the multi-source prompt and asks an LLMClient to produce a
    structured JSON summary. Provider-agnostic — the worker injects whichever
    LLMClient (Groq, Gemini, Fallback over both) it wants used.
    """

    SYSTEM_PROMPT = (
        "You are a news summarizer for an Indian news app called VaartaAI. "
        "Write crisp, neutral, jargon-free summaries a college student can understand. "
        "Always respond in valid JSON only. No extra text outside the JSON."
    )

    def __init__(
        self,
        article_repo: ArticleRepository,
        settings: Settings,
        llm: LLMClient,
    ):
        self._article_repo = article_repo
        self._max_articles = settings.max_articles_per_summary
        self._llm = llm

    def summarize(self, cluster_id: int) -> Summary | None:
        articles = self._article_repo.get_by_cluster(cluster_id, limit=self._max_articles)
        if not articles:
            logger.warning("No articles found for cluster #%d", cluster_id)
            return None

        prompt = self._build_prompt(articles)

        try:
            raw = self._llm.complete_json(self.SYSTEM_PROMPT, prompt, max_tokens=1024)
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM response for cluster #%d: %s", cluster_id, e)
            return None
        # Quota / API errors propagate so the caller can apply policy.

        return Summary(
            cluster_id=cluster_id,
            summary_text=data.get("summary", ""),
            why_it_matters=data.get("why_it_matters", ""),
            deep_explainer=data.get("background", ""),
            category=data.get("category", "general"),
            entities=data.get("entities", []),
            topics=data.get("topics", []),
            is_safe=data.get("is_safe", True),
            sources_agree=data.get("sources_agree", True),
        )

    def _build_prompt(self, articles: list[Article]) -> str:
        sources_text = ""
        for i, article in enumerate(articles, 1):
            sources_text += (
                f"\nSOURCE {i} ({article.source.name}, trust: {article.source.trust_score}/5):\n"
                f"Title: {article.title}\n"
                f"Body: {article.body_text[:600]}\n"
            )

        return f"""Summarize this news story from multiple sources.
{sources_text}
Respond ONLY in this exact JSON format:
{{
  "summary": "<55-65 word neutral summary>",
  "why_it_matters": "<1-2 sentences. Why should an average Indian reader care? Be specific — money, jobs, rights, safety, daily life. Never be vague.>",
  "background": "<3-5 sentences of backstory. What led to this? Key prior events, decisions, or context a reader needs to fully understand this story. Be factual and specific.>",
  "category": "<politics|business|tech|sports|entertainment|health|science|general>",
  "entities": ["list", "of", "key", "names"],
  "topics": ["list", "of", "key", "topics"],
  "is_safe": true,
  "sources_agree": true
}}"""
