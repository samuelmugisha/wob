DROP VIEW IF EXISTS knowledge_base_chunks;

DROP INDEX IF EXISTS idx_documents_processing_queue;

ALTER TABLE documents
    DROP COLUMN processed_at,
    DROP COLUMN next_attempt_at,
    DROP COLUMN processing_started_at,
    DROP COLUMN processing_attempts;
