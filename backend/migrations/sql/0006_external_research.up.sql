-- External research of credible public sources (FR-13, spec §6).

CREATE TABLE research_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finalist_category_id UUID NOT NULL REFERENCES finalist_categories (id),
    status job_status NOT NULL DEFAULT 'queued',
    llm_model TEXT NOT NULL,
    served_by_models TEXT[] NOT NULL DEFAULT '{}',
    prompt_version TEXT NOT NULL,
    claim_ids UUID[] NOT NULL DEFAULT '{}',
    usage JSONB NOT NULL DEFAULT '{}'::jsonb,
    searches INTEGER NOT NULL DEFAULT 0,
    pages_fetched INTEGER NOT NULL DEFAULT 0,
    findings_created INTEGER NOT NULL DEFAULT 0,
    -- Claims with no public trace. Informational only: never counts against a nominee.
    not_found JSONB NOT NULL DEFAULT '[]'::jsonb,
    identity_concerns JSONB NOT NULL DEFAULT '[]'::jsonb,
    discarded JSONB NOT NULL DEFAULT '[]'::jsonb,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ,
    error TEXT,
    requested_by UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);
CREATE INDEX idx_research_runs_finalist ON research_runs (finalist_category_id, created_at DESC);
CREATE UNIQUE INDEX uq_research_runs_active ON research_runs (finalist_category_id)
    WHERE status IN ('queued', 'running');

ALTER TABLE external_sources
    ADD COLUMN research_run_id UUID REFERENCES research_runs (id),
    ADD COLUMN claim_id UUID,
    ADD COLUMN relation evidence_relation,
    ADD COLUMN quote TEXT,
    ADD COLUMN source_type TEXT CHECK (source_type IN (
        'official_registry', 'regulator', 'organisation_website', 'annual_report',
        'news_media', 'professional_body', 'other'
    )),
    ADD COLUMN identity_confidence quality_level,
    ADD COLUMN identity_notes TEXT,
    ADD COLUMN identity_confirmed BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN review_notes TEXT,
    ADD COLUMN superseded_at TIMESTAMPTZ,
    -- A finding may only concern a claim of the same finalist.
    ADD CONSTRAINT external_sources_claim_fk FOREIGN KEY (claim_id, finalist_category_id)
        REFERENCES claims (id, finalist_category_id),
    ADD CONSTRAINT external_sources_review_complete CHECK (
        (reviewer_outcome = 'pending') = (reviewed_by IS NULL AND reviewed_at IS NULL)
    ),
    -- Accepting a source requires a credibility rating and, unless identity was certain,
    -- explicit confirmation that the page is about this nominee.
    ADD CONSTRAINT external_sources_accept_rules CHECK (
        reviewer_outcome <> 'accepted'
        OR (credibility IS NOT NULL
            AND (identity_confidence = 'high' OR identity_confirmed))
    );
CREATE INDEX idx_external_sources_claim ON external_sources (claim_id);
