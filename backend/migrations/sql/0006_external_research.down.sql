DROP INDEX IF EXISTS idx_external_sources_claim;
ALTER TABLE external_sources
    DROP CONSTRAINT external_sources_accept_rules,
    DROP CONSTRAINT external_sources_review_complete,
    DROP CONSTRAINT external_sources_claim_fk,
    DROP COLUMN superseded_at,
    DROP COLUMN review_notes,
    DROP COLUMN identity_confirmed,
    DROP COLUMN identity_notes,
    DROP COLUMN identity_confidence,
    DROP COLUMN source_type,
    DROP COLUMN quote,
    DROP COLUMN relation,
    DROP COLUMN claim_id,
    DROP COLUMN research_run_id;
DROP TABLE IF EXISTS research_runs;
