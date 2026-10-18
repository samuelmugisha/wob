-- Claim extraction runs (FR-06) and the extra claim fields they produce.

CREATE TABLE claim_extraction_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finalist_category_id UUID NOT NULL REFERENCES finalist_categories (id),
    status job_status NOT NULL DEFAULT 'queued',
    llm_model TEXT NOT NULL,
    served_by_models TEXT[] NOT NULL DEFAULT '{}',
    prompt_version TEXT NOT NULL,
    input_chunk_ids UUID[] NOT NULL DEFAULT '{}',
    batches INTEGER NOT NULL DEFAULT 0,
    usage JSONB NOT NULL DEFAULT '{}'::jsonb,
    contradictions JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_information JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- Claims or quotes dropped because their evidence could not be verified.
    discarded JSONB NOT NULL DEFAULT '[]'::jsonb,
    claims_created INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ,
    error TEXT,
    requested_by UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);
CREATE INDEX idx_claim_runs_finalist ON claim_extraction_runs (finalist_category_id, created_at DESC);
-- At most one queued or running extraction per finalist.
CREATE UNIQUE INDEX uq_claim_runs_active ON claim_extraction_runs (finalist_category_id)
    WHERE status IN ('queued', 'running');

ALTER TABLE claims
    ADD COLUMN extraction_run_id UUID REFERENCES claim_extraction_runs (id),
    ADD COLUMN claim_type TEXT CHECK (claim_type IN (
        'position', 'achievement', 'outcome', 'award', 'qualification', 'membership',
        'advocacy', 'other'
    )),
    ADD COLUMN role TEXT,
    ADD COLUMN period_start_precision TEXT CHECK (period_start_precision IN ('year', 'month', 'day')),
    ADD COLUMN period_end_precision TEXT CHECK (period_end_precision IN ('year', 'month', 'day')),
    ADD COLUMN limitations TEXT,
    -- Set when a later extraction run replaces this claim; reviews stay attached for history.
    ADD COLUMN superseded_at TIMESTAMPTZ;
CREATE INDEX idx_claims_current ON claims (finalist_category_id) WHERE superseded_at IS NULL;
