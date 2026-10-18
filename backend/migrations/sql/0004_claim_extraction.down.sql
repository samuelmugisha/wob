DROP INDEX IF EXISTS idx_claims_current;
ALTER TABLE claims
    DROP COLUMN superseded_at,
    DROP COLUMN limitations,
    DROP COLUMN period_end_precision,
    DROP COLUMN period_start_precision,
    DROP COLUMN role,
    DROP COLUMN claim_type,
    DROP COLUMN extraction_run_id;
DROP TABLE IF EXISTS claim_extraction_runs;
