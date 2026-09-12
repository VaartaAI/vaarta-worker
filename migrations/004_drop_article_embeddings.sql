-- Remove the unused title-embedding column.
--
-- 003_article_embeddings.sql (applied in production on 2026-05-09, never
-- committed to this repo) added articles.title_embedding vector(384) plus an
-- HNSW index for semantic clustering. No code in vaarta-worker or vaarta-api
-- reads or writes it; only 118 rows from that one day ever had a value.
-- Clustering uses pg_trgm title similarity. Drop the column, its index, and
-- the pgvector extension, which nothing else uses.
--
-- Idempotent: safe on databases where 003 was never applied.

DROP INDEX IF EXISTS idx_articles_title_embedding;
ALTER TABLE articles DROP COLUMN IF EXISTS title_embedding;
DROP EXTENSION IF EXISTS vector;
