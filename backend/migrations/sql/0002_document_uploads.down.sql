CREATE OR REPLACE FUNCTION protect_document_original() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.filename IS DISTINCT FROM OLD.filename
        OR NEW.storage_key IS DISTINCT FROM OLD.storage_key
        OR NEW.sha256_hash IS DISTINCT FROM OLD.sha256_hash
        OR NEW.mime_type IS DISTINCT FROM OLD.mime_type
        OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
        OR NEW.uploaded_at IS DISTINCT FROM OLD.uploaded_at
    THEN
        RAISE EXCEPTION 'original file metadata of document % is immutable', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

DROP INDEX IF EXISTS uq_documents_active_hash;

ALTER TABLE documents
    DROP CONSTRAINT documents_withdrawal_complete,
    DROP CONSTRAINT documents_archive_member_has_archive,
    DROP COLUMN withdrawal_reason,
    DROP COLUMN withdrawn_by,
    DROP COLUMN withdrawn_at,
    DROP COLUMN archive_member,
    DROP COLUMN archive_name;

ALTER TABLE imports DROP COLUMN finalist_category_id;
