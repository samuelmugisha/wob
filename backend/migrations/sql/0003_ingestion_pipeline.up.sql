-- Ingestion worker: job bookkeeping on documents, embedding dimension, retrieval view.

ALTER TABLE documents
    ADD COLUMN processing_attempts INTEGER NOT NULL DEFAULT 0 CHECK (processing_attempts >= 0),
    ADD COLUMN processing_started_at TIMESTAMPTZ,
    ADD COLUMN next_attempt_at TIMESTAMPTZ,
    ADD COLUMN processed_at TIMESTAMPTZ;

CREATE INDEX idx_documents_processing_queue ON documents (uploaded_at)
    WHERE withdrawn_at IS NULL AND processing_status NOT IN ('indexed', 'rejected');

-- Match the configured embedding model. Fails if embeddings of another size are stored,
-- which then require re-embedding rather than a silent type change.
DROP INDEX idx_chunks_embedding;
ALTER TABLE document_chunks ALTER COLUMN embedding TYPE VECTOR(__EMBEDDING_DIM__);
CREATE INDEX idx_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops);

-- The knowledge base proper: chunks of indexed, non-withdrawn documents. Retrieval reads
-- this view (always filtered by finalist_category_id) rather than document_chunks directly.
CREATE VIEW knowledge_base_chunks AS
SELECT c.*, d.filename, d.source_type
FROM document_chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.withdrawn_at IS NULL AND d.processing_status = 'indexed';
