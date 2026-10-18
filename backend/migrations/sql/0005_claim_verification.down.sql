DROP TABLE IF EXISTS contradiction_resolutions;
ALTER TABLE claim_extraction_runs DROP COLUMN claims_carried_forward;
ALTER TABLE verification_reviews
    DROP CONSTRAINT verification_reviews_notes_required,
    DROP COLUMN carried_from,
    DROP COLUMN credibility,
    DROP COLUMN sufficiency;
