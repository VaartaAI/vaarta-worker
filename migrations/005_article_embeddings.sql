-- Semantic clustering: embedding per article.
--
-- Trigram title similarity (pg_trgm) only catches near-identical headlines;
-- two papers wording the same event differently score ~0.2-0.3 and end up in
-- separate clusters. Each new article now gets a 384-dim embedding of
-- "title. body excerpt" from Gemini (infra/embeddings), and clustering joins
-- the nearest recent article's cluster when cosine similarity clears the
-- configured threshold. Trigram matching remains as the fallback path.
--
-- Column is nullable: rows ingested before this migration, and rows saved
-- while the embedding API was unavailable, have NULL and are simply skipped
-- by the vector search. `python main.py backfill-embeddings` fills recent
-- gaps.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE articles ADD COLUMN IF NOT EXISTS embedding vector(384);

-- HNSW for approximate nearest-neighbour by cosine distance (<=>).
CREATE INDEX IF NOT EXISTS idx_articles_embedding
    ON articles USING hnsw (embedding vector_cosine_ops);
