-- WOB Awards 2026 RAG ranking system: initial schema (spec §8).
-- __EMBEDDING_DIM__ is substituted from settings.embedding_dim by the Alembic revision.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Enumerated types
-- ---------------------------------------------------------------------------
CREATE TYPE user_role AS ENUM ('admin', 'secretariat', 'reviewer', 'judge', 'committee');
CREATE TYPE rubric_status AS ENUM ('draft', 'approved', 'frozen');
CREATE TYPE weighting_mode AS ENUM ('equal', 'weighted');
CREATE TYPE job_status AS ENUM ('queued', 'running', 'succeeded', 'failed', 'cancelled');
CREATE TYPE processing_status AS ENUM (
    'pending', 'scanning', 'extracting', 'extracted', 'chunking', 'indexed', 'failed', 'rejected'
);
CREATE TYPE source_type AS ENUM ('nomination_form', 'supporting_document');
CREATE TYPE claim_status AS ENUM ('verified', 'corroborated', 'unverified', 'missing', 'disputed');
CREATE TYPE evidence_relation AS ENUM ('supports', 'contradicts');
CREATE TYPE quality_level AS ENUM ('high', 'medium', 'low');
CREATE TYPE review_outcome AS ENUM ('pending', 'accepted', 'rejected');
CREATE TYPE evidence_sufficiency AS ENUM ('sufficient', 'limited', 'insufficient');
CREATE TYPE assessment_status AS ENUM ('proposed', 'reviewed', 'approved', 'rejected');
CREATE TYPE report_kind AS ENUM ('individual', 'category');

-- ---------------------------------------------------------------------------
-- Shared trigger functions
-- ---------------------------------------------------------------------------
CREATE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% on % is not permitted: rows are append-only', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$;

-- ---------------------------------------------------------------------------
-- Users and the official rating scale
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role user_role NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_users_email ON users (lower(email));

-- Fixed committee scale (spec §2). Reference data, not editable.
CREATE TABLE rating_scale (
    rating SMALLINT PRIMARY KEY CHECK (rating BETWEEN 1 AND 5),
    definition TEXT NOT NULL
);
INSERT INTO rating_scale (rating, definition) VALUES
    (1, 'Not demonstrated / no evidence'),
    (2, 'Weak evidence'),
    (3, 'Adequate evidence'),
    (4, 'Strong evidence'),
    (5, 'Exceptional, well-evidenced');
CREATE TRIGGER rating_scale_fixed
    BEFORE UPDATE OR DELETE ON rating_scale
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- ---------------------------------------------------------------------------
-- Categories and versioned rubrics (spec §7)
-- ---------------------------------------------------------------------------
CREATE TABLE award_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    award_year SMALLINT NOT NULL DEFAULT 2026,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (award_year, code)
);

CREATE TABLE rubric_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id UUID NOT NULL REFERENCES award_categories (id),
    version INTEGER NOT NULL CHECK (version > 0),
    status rubric_status NOT NULL DEFAULT 'draft',
    weighting weighting_mode NOT NULL DEFAULT 'equal',
    eligibility_rules JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes TEXT,
    approved_by UUID REFERENCES users (id),
    approved_at TIMESTAMPTZ,
    frozen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (category_id, version),
    UNIQUE (id, category_id),
    CHECK (status = 'draft' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)),
    CHECK ((status = 'frozen') = (frozen_at IS NOT NULL))
);

CREATE TABLE rubric_criteria (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rubric_version_id UUID NOT NULL REFERENCES rubric_versions (id),
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    evidence_expectations TEXT,
    weight NUMERIC(6, 3) CHECK (weight IS NULL OR weight > 0),
    position SMALLINT NOT NULL,
    UNIQUE (rubric_version_id, code),
    UNIQUE (rubric_version_id, position)
);

-- Rubrics are created as drafts, may only be edited as drafts, and are immutable once frozen.
CREATE FUNCTION guard_rubric_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'rubric versions must be created as drafts'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'frozen' THEN
        RAISE EXCEPTION 'rubric version % is frozen', OLD.id USING ERRCODE = 'restrict_violation';
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'only draft rubric versions can be deleted'
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN OLD;
    END IF;

    IF NEW.status = 'frozen' THEN
        IF NOT EXISTS (SELECT 1 FROM rubric_criteria WHERE rubric_version_id = NEW.id) THEN
            RAISE EXCEPTION 'rubric version % has no criteria', NEW.id
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.weighting = 'weighted' AND EXISTS (
            SELECT 1 FROM rubric_criteria WHERE rubric_version_id = NEW.id AND weight IS NULL
        ) THEN
            RAISE EXCEPTION 'weighted rubric version % has criteria without weights', NEW.id
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER rubric_versions_guard
    BEFORE INSERT OR UPDATE OR DELETE ON rubric_versions
    FOR EACH ROW EXECUTE FUNCTION guard_rubric_version();

CREATE FUNCTION guard_rubric_criteria() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        IF (SELECT status FROM rubric_versions WHERE id = OLD.rubric_version_id) <> 'draft' THEN
            RAISE EXCEPTION 'criteria of non-draft rubric version % cannot change', OLD.rubric_version_id
                USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        IF (SELECT status FROM rubric_versions WHERE id = NEW.rubric_version_id) <> 'draft' THEN
            RAISE EXCEPTION 'criteria of non-draft rubric version % cannot change', NEW.rubric_version_id
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    RETURN OLD;
END
$$;
CREATE TRIGGER rubric_criteria_guard
    BEFORE INSERT OR UPDATE OR DELETE ON rubric_criteria
    FOR EACH ROW EXECUTE FUNCTION guard_rubric_criteria();

-- ---------------------------------------------------------------------------
-- Finalists and shortlisted category membership
-- ---------------------------------------------------------------------------
CREATE TABLE finalists (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name TEXT NOT NULL,
    organisation TEXT,
    position_title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE finalist_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finalist_id UUID NOT NULL REFERENCES finalists (id),
    category_id UUID NOT NULL REFERENCES award_categories (id),
    -- Eligibility issues are flagged for review, never used to drop a finalist (spec §2).
    eligibility_flagged BOOLEAN NOT NULL DEFAULT false,
    eligibility_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (finalist_id, category_id)
);
CREATE INDEX idx_finalist_categories_category ON finalist_categories (category_id);

-- ---------------------------------------------------------------------------
-- Imports, documents and chunks (spec §5)
-- ---------------------------------------------------------------------------
CREATE TABLE imports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key TEXT NOT NULL UNIQUE,
    status job_status NOT NULL DEFAULT 'queued',
    file_count INTEGER NOT NULL DEFAULT 0 CHECK (file_count >= 0),
    error TEXT,
    created_by UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

-- finalist_category_id is nullable (unlike the spec excerpt) so files can be stored on import
-- before an administrator confirms which finalist they belong to (FR-03).
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    import_id UUID REFERENCES imports (id),
    finalist_category_id UUID REFERENCES finalist_categories (id),
    mapping_confirmed_by UUID REFERENCES users (id),
    mapping_confirmed_at TIMESTAMPTZ,
    filename TEXT NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    sha256_hash CHAR(64) NOT NULL CHECK (sha256_hash ~ '^[0-9a-f]{64}$'),
    mime_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    source_type source_type NOT NULL DEFAULT 'supporting_document',
    processing_status processing_status NOT NULL DEFAULT 'pending',
    processing_error TEXT,
    extraction_version TEXT,
    extraction_quality JSONB NOT NULL DEFAULT '{}'::jsonb,
    uploaded_by UUID REFERENCES users (id),
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (id, finalist_category_id),
    CHECK ((mapping_confirmed_by IS NULL) = (mapping_confirmed_at IS NULL)),
    CHECK (mapping_confirmed_at IS NULL OR finalist_category_id IS NOT NULL)
);
CREATE INDEX idx_documents_finalist_category ON documents (finalist_category_id);
CREATE INDEX idx_documents_sha256 ON documents (sha256_hash);

-- Originals are stored immutably (spec §5.1).
CREATE FUNCTION protect_document_original() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE TRIGGER documents_protect_original
    BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION protect_document_original();
CREATE TRIGGER documents_no_delete
    BEFORE DELETE ON documents
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- finalist_category_id is denormalised onto chunks so retrieval can filter by finalist before
-- the vector/lexical search (spec §5.3). The composite FK keeps it equal to the document's.
CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL,
    finalist_category_id UUID NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    page_number INTEGER CHECK (page_number > 0),
    section TEXT,
    content TEXT NOT NULL,
    token_count INTEGER CHECK (token_count >= 0),
    content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    embedding VECTOR(__EMBEDDING_DIM__),
    embedding_model TEXT,
    extraction_version TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index),
    UNIQUE (id, finalist_category_id),
    FOREIGN KEY (document_id, finalist_category_id)
        REFERENCES documents (id, finalist_category_id),
    CHECK ((embedding IS NULL) = (embedding_model IS NULL))
);
CREATE INDEX idx_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_chunks_content_tsv ON document_chunks USING gin (content_tsv);
CREATE INDEX idx_chunks_finalist_category ON document_chunks (finalist_category_id);

-- Evidence is only indexed after an administrator confirms the document's finalist (FR-03).
CREATE FUNCTION require_confirmed_mapping() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM documents
        WHERE id = NEW.document_id AND mapping_confirmed_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'document % has no administrator-confirmed finalist mapping', NEW.document_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER document_chunks_require_mapping
    BEFORE INSERT OR UPDATE OF document_id, finalist_category_id ON document_chunks
    FOR EACH ROW EXECUTE FUNCTION require_confirmed_mapping();

-- ---------------------------------------------------------------------------
-- Claims, external sources and verification (spec §6)
-- ---------------------------------------------------------------------------
CREATE TABLE claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finalist_category_id UUID NOT NULL REFERENCES finalist_categories (id),
    wording TEXT NOT NULL,
    entity TEXT,
    period_start DATE,
    period_end DATE,
    period_text TEXT,
    quantitative_outcomes JSONB NOT NULL DEFAULT '[]'::jsonb,
    status claim_status NOT NULL DEFAULT 'unverified',
    extraction_model TEXT,
    extraction_prompt_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (id, finalist_category_id)
);
CREATE INDEX idx_claims_finalist_category ON claims (finalist_category_id);

CREATE TABLE external_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finalist_category_id UUID NOT NULL REFERENCES finalist_categories (id),
    publisher TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    published_at DATE,
    retrieved_at TIMESTAMPTZ NOT NULL,
    evidence_passage TEXT NOT NULL,
    content_sha256 CHAR(64) CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    credibility quality_level,
    reviewer_outcome review_outcome NOT NULL DEFAULT 'pending',
    reviewed_by UUID REFERENCES users (id),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (id, finalist_category_id)
);
CREATE INDEX idx_external_sources_finalist_category ON external_sources (finalist_category_id);

-- Composite FKs guarantee a claim can only cite evidence of its own finalist.
CREATE TABLE claim_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL,
    finalist_category_id UUID NOT NULL,
    chunk_id UUID,
    external_source_id UUID,
    relation evidence_relation NOT NULL,
    quoted_span TEXT NOT NULL,
    relevance quality_level,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (claim_id, finalist_category_id) REFERENCES claims (id, finalist_category_id),
    FOREIGN KEY (chunk_id, finalist_category_id)
        REFERENCES document_chunks (id, finalist_category_id),
    FOREIGN KEY (external_source_id, finalist_category_id)
        REFERENCES external_sources (id, finalist_category_id),
    CHECK (num_nonnulls(chunk_id, external_source_id) = 1)
);
CREATE INDEX idx_claim_evidence_claim ON claim_evidence (claim_id);

CREATE TABLE verification_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES claims (id),
    reviewer_id UUID NOT NULL REFERENCES users (id),
    previous_status claim_status,
    decision claim_status NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_verification_reviews_claim ON verification_reviews (claim_id);
CREATE TRIGGER verification_reviews_append_only
    BEFORE UPDATE OR DELETE ON verification_reviews
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- ---------------------------------------------------------------------------
-- Assessments (spec §7.1, §10.2)
-- ---------------------------------------------------------------------------
CREATE TABLE assessment_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id UUID NOT NULL REFERENCES award_categories (id),
    rubric_version_id UUID NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    llm_model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    reranker_model TEXT,
    retrieval_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    status job_status NOT NULL DEFAULT 'queued',
    error TEXT,
    requested_by UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    FOREIGN KEY (rubric_version_id, category_id) REFERENCES rubric_versions (id, category_id)
);
CREATE INDEX idx_assessment_runs_category ON assessment_runs (category_id);

CREATE TABLE criterion_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES assessment_runs (id),
    finalist_category_id UUID NOT NULL REFERENCES finalist_categories (id),
    criterion_id UUID NOT NULL REFERENCES rubric_criteria (id),
    rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    rationale TEXT NOT NULL,
    sufficiency evidence_sufficiency NOT NULL,
    verification_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    review_required BOOLEAN NOT NULL DEFAULT true,
    status assessment_status NOT NULL DEFAULT 'proposed',
    reviewed_by UUID REFERENCES users (id),
    reviewed_at TIMESTAMPTZ,
    raw_output JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, finalist_category_id, criterion_id),
    UNIQUE (id, finalist_category_id)
);
CREATE INDEX idx_criterion_assessments_finalist_category
    ON criterion_assessments (finalist_category_id);

CREATE TABLE assessment_citations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    criterion_assessment_id UUID NOT NULL,
    finalist_category_id UUID NOT NULL,
    chunk_id UUID,
    external_source_id UUID,
    relation evidence_relation NOT NULL,
    quoted_span TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (criterion_assessment_id, finalist_category_id)
        REFERENCES criterion_assessments (id, finalist_category_id),
    FOREIGN KEY (chunk_id, finalist_category_id)
        REFERENCES document_chunks (id, finalist_category_id),
    FOREIGN KEY (external_source_id, finalist_category_id)
        REFERENCES external_sources (id, finalist_category_id),
    CHECK (num_nonnulls(chunk_id, external_source_id) = 1)
);
CREATE INDEX idx_assessment_citations_assessment ON assessment_citations (criterion_assessment_id);

-- ---------------------------------------------------------------------------
-- Rankings (spec §7.2): immutable snapshots
-- ---------------------------------------------------------------------------
CREATE TABLE ranking_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id UUID NOT NULL REFERENCES award_categories (id),
    run_id UUID NOT NULL REFERENCES assessment_runs (id),
    rubric_version_id UUID NOT NULL REFERENCES rubric_versions (id),
    weighting weighting_mode NOT NULL,
    calculation_version TEXT NOT NULL,
    is_provisional BOOLEAN NOT NULL DEFAULT true,
    created_by UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Finalists with unassessed criteria appear with no score/rank rather than being omitted.
CREATE TABLE ranking_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id UUID NOT NULL REFERENCES ranking_snapshots (id),
    finalist_category_id UUID NOT NULL REFERENCES finalist_categories (id),
    score NUMERIC CHECK (score BETWEEN 1 AND 5),
    rank INTEGER CHECK (rank > 0),
    is_tie BOOLEAN NOT NULL DEFAULT false,
    criteria_assessed INTEGER NOT NULL CHECK (criteria_assessed >= 0),
    criteria_total INTEGER NOT NULL CHECK (criteria_total > 0),
    missing_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (snapshot_id, finalist_category_id),
    CHECK (criteria_assessed <= criteria_total),
    CHECK ((score IS NOT NULL) = (criteria_assessed = criteria_total)),
    CHECK (rank IS NULL OR score IS NOT NULL)
);
CREATE TRIGGER ranking_snapshots_append_only
    BEFORE UPDATE OR DELETE ON ranking_snapshots
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER ranking_entries_append_only
    BEFORE UPDATE OR DELETE ON ranking_entries
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- ---------------------------------------------------------------------------
-- Reports and audit
-- ---------------------------------------------------------------------------
CREATE TABLE reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind report_kind NOT NULL,
    category_id UUID NOT NULL REFERENCES award_categories (id),
    finalist_category_id UUID REFERENCES finalist_categories (id),
    snapshot_id UUID NOT NULL REFERENCES ranking_snapshots (id),
    status job_status NOT NULL DEFAULT 'queued',
    storage_key TEXT UNIQUE,
    sha256_hash CHAR(64) CHECK (sha256_hash ~ '^[0-9a-f]{64}$'),
    error TEXT,
    requested_by UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CHECK ((kind = 'individual') = (finalist_category_id IS NOT NULL))
);

CREATE TABLE audit_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id UUID REFERENCES users (id),
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id UUID,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_audit_events_entity ON audit_events (entity_type, entity_id);
CREATE TRIGGER audit_events_append_only
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER audit_events_no_truncate
    BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();
