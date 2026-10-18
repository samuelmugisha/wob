ALTER TABLE ranking_entries DROP COLUMN criterion_ratings, DROP COLUMN unreviewed_criteria;
ALTER TABLE ranking_snapshots DROP COLUMN rubric_status;
ALTER TABLE criterion_assessments
    DROP CONSTRAINT criterion_assessments_review_complete,
    DROP CONSTRAINT criterion_assessments_adjustment_reason,
    DROP COLUMN review_notes,
    DROP COLUMN reviewer_rating,
    DROP COLUMN limitations;
DROP INDEX IF EXISTS uq_assessment_runs_active;
ALTER TABLE assessment_runs
    DROP COLUMN rubric_status,
    DROP COLUMN next_attempt_at,
    DROP COLUMN attempts,
    DROP COLUMN usage,
    DROP COLUMN served_by_models,
    DROP COLUMN items_done,
    DROP COLUMN items_total;
