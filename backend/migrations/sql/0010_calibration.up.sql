-- Calibration of AI ratings against blind human benchmark ratings (FR-15, spec §16).

CREATE TABLE calibration_studies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id UUID NOT NULL REFERENCES award_categories (id),
    run_id UUID NOT NULL REFERENCES assessment_runs (id),
    rubric_version_id UUID NOT NULL REFERENCES rubric_versions (id),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'cancelled')),
    outcome TEXT CHECK (outcome IN ('passed', 'failed', 'inconclusive')),
    results JSONB,
    thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ,
    CHECK ((status = 'closed') = (outcome IS NOT NULL AND results IS NOT NULL AND closed_at IS NOT NULL))
);
CREATE INDEX idx_calibration_studies_category ON calibration_studies (category_id, created_at DESC);

CREATE TABLE calibration_raters (
    study_id UUID NOT NULL REFERENCES calibration_studies (id),
    user_id UUID NOT NULL REFERENCES users (id),
    completed_at TIMESTAMPTZ,
    -- The rater confirmed they did not see the AI's ratings before rating.
    attested_blind BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (study_id, user_id),
    CHECK (completed_at IS NULL OR attested_blind)
);

CREATE TABLE calibration_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    study_id UUID NOT NULL REFERENCES calibration_studies (id),
    finalist_category_id UUID NOT NULL REFERENCES finalist_categories (id),
    criterion_id UUID NOT NULL REFERENCES rubric_criteria (id),
    position INTEGER NOT NULL,
    UNIQUE (study_id, finalist_category_id, criterion_id)
);

CREATE TABLE calibration_ratings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id UUID NOT NULL REFERENCES calibration_items (id),
    rater_id UUID NOT NULL REFERENCES users (id),
    rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (item_id, rater_id)
);

-- Closed studies are a permanent record: their ratings and results cannot change.
CREATE FUNCTION guard_closed_calibration() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    study_status TEXT;
BEGIN
    SELECT s.status INTO study_status FROM calibration_studies s
    JOIN calibration_items i ON i.study_id = s.id
    WHERE i.id = COALESCE(NEW.item_id, OLD.item_id);
    IF study_status <> 'open' THEN
        RAISE EXCEPTION 'calibration study is %; its ratings cannot change', study_status
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER calibration_ratings_guard
    BEFORE INSERT OR UPDATE OR DELETE ON calibration_ratings
    FOR EACH ROW EXECUTE FUNCTION guard_closed_calibration();

CREATE FUNCTION guard_calibration_study() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'open' THEN
        RAISE EXCEPTION 'calibration study % is %', OLD.id, OLD.status
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER calibration_studies_guard
    BEFORE UPDATE OR DELETE ON calibration_studies
    FOR EACH ROW EXECUTE FUNCTION guard_calibration_study();
