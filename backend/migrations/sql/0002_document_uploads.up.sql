-- Coordinator uploads: archive provenance, withdrawal of mistaken uploads, duplicate detection.

ALTER TABLE imports ADD COLUMN finalist_category_id UUID REFERENCES finalist_categories (id);

ALTER TABLE documents
    ADD COLUMN archive_name TEXT,
    ADD COLUMN archive_member TEXT,
    ADD COLUMN withdrawn_at TIMESTAMPTZ,
    ADD COLUMN withdrawn_by UUID REFERENCES users (id),
    ADD COLUMN withdrawal_reason TEXT,
    ADD CONSTRAINT documents_archive_member_has_archive
        CHECK (archive_member IS NULL OR archive_name IS NOT NULL),
    ADD CONSTRAINT documents_withdrawal_complete CHECK (
        (withdrawn_at IS NULL AND withdrawn_by IS NULL AND withdrawal_reason IS NULL)
        OR (withdrawn_at IS NOT NULL AND withdrawn_by IS NOT NULL AND withdrawal_reason IS NOT NULL)
    );

-- The same file can't be active twice for one finalist in one category.
CREATE UNIQUE INDEX uq_documents_active_hash
    ON documents (finalist_category_id, sha256_hash)
    WHERE withdrawn_at IS NULL;

-- Originals stay immutable; withdrawal is one-way. Withdrawn documents are kept for audit
-- but excluded from the knowledge base.
CREATE OR REPLACE FUNCTION protect_document_original() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.filename IS DISTINCT FROM OLD.filename
        OR NEW.storage_key IS DISTINCT FROM OLD.storage_key
        OR NEW.sha256_hash IS DISTINCT FROM OLD.sha256_hash
        OR NEW.mime_type IS DISTINCT FROM OLD.mime_type
        OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
        OR NEW.uploaded_at IS DISTINCT FROM OLD.uploaded_at
        OR NEW.archive_name IS DISTINCT FROM OLD.archive_name
        OR NEW.archive_member IS DISTINCT FROM OLD.archive_member
    THEN
        RAISE EXCEPTION 'original file metadata of document % is immutable', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.withdrawn_at IS NOT NULL AND (
        NEW.withdrawn_at IS DISTINCT FROM OLD.withdrawn_at
        OR NEW.withdrawn_by IS DISTINCT FROM OLD.withdrawn_by
        OR NEW.withdrawal_reason IS DISTINCT FROM OLD.withdrawal_reason
    ) THEN
        RAISE EXCEPTION 'withdrawal of document % cannot be changed', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;
