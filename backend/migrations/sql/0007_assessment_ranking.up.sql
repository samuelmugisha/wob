-- Criterion assessment (FR-08), quality review and provisional ranking (FR-09).

ALTER TABLE assessment_runs
    ADD COLUMN items_total INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN items_done INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN served_by_models TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN usage JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN next_attempt_at TIMESTAMPTZ,
    ADD COLUMN rubric_status rubric_status;
CREATE UNIQUE INDEX uq_assessment_runs_active ON assessment_runs (category_id)
    WHERE status IN ('queued', 'running');

ALTER TABLE criterion_assessments
    ADD COLUMN limitations TEXT,
    -- A reviewer may adjust the AI's proposed rating, with a reason; the original is kept.
    ADD COLUMN reviewer_rating SMALLINT CHECK (reviewer_rating BETWEEN 1 AND 5),
    ADD COLUMN review_notes TEXT,
    ADD CONSTRAINT criterion_assessments_adjustment_reason CHECK (
        reviewer_rating IS NULL OR length(btrim(coalesce(review_notes, ''))) > 0
    ),
    ADD CONSTRAINT criterion_assessments_review_complete CHECK (
        (status = 'proposed') = (reviewed_by IS NULL AND reviewed_at IS NULL)
    );

-- The rubric's status when the ranking was calculated: only 'frozen' rankings are production.
ALTER TABLE ranking_snapshots ADD COLUMN rubric_status rubric_status NOT NULL DEFAULT 'draft';
ALTER TABLE ranking_entries
    ADD COLUMN unreviewed_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN criterion_ratings JSONB NOT NULL DEFAULT '{}'::jsonb;
