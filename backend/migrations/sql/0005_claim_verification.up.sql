-- Reviewer verification of claims (FR-07, spec §6).

ALTER TABLE verification_reviews
    ADD COLUMN sufficiency evidence_sufficiency,
    ADD COLUMN credibility quality_level,
    -- Set when a review is carried forward from an identical claim of an earlier extraction.
    ADD COLUMN carried_from UUID REFERENCES verification_reviews (id),
    ADD CONSTRAINT verification_reviews_notes_required CHECK (
        decision = 'verified' OR (notes IS NOT NULL AND length(btrim(notes)) > 0)
    );

ALTER TABLE claim_extraction_runs
    ADD COLUMN claims_carried_forward INTEGER NOT NULL DEFAULT 0;

-- Manual resolution of contradictions found during extraction. Append-only: the latest row
-- for a (run, index) pair is the current resolution.
CREATE TABLE contradiction_resolutions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    extraction_run_id UUID NOT NULL REFERENCES claim_extraction_runs (id),
    contradiction_index INTEGER NOT NULL CHECK (contradiction_index >= 0),
    resolution TEXT NOT NULL CHECK (length(btrim(resolution)) > 0),
    resolved_by UUID NOT NULL REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_contradiction_resolutions_run
    ON contradiction_resolutions (extraction_run_id, contradiction_index, created_at DESC);
CREATE TRIGGER contradiction_resolutions_append_only
    BEFORE UPDATE OR DELETE ON contradiction_resolutions
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
