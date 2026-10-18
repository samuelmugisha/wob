-- Data protection controls (docs/operations/data-protection-review.md): consent records,
-- human-only assessment, retention dates, and a sanctioned purge path.

-- Append-only consent history per nomination; the latest row is the current consent.
CREATE TABLE finalist_consents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finalist_category_id UUID NOT NULL REFERENCES finalist_categories (id),
    notice_version TEXT NOT NULL,
    assessment BOOLEAN NOT NULL,      -- part A: assessment of the nomination (s.7, s.9(3)(b))
    ai_processing BOOLEAN NOT NULL,   -- part B: AI-assisted assessment abroad (s.19, Reg 30)
    web_research BOOLEAN NOT NULL,    -- part C: public-source checks
    method TEXT NOT NULL CHECK (method IN ('signed_form', 'email', 'online', 'other')),
    reference TEXT,                   -- where the signed form or email is kept
    recorded_by UUID REFERENCES users (id),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (assessment OR (NOT ai_processing AND NOT web_research))
);
CREATE INDEX idx_finalist_consents_current ON finalist_consents (finalist_category_id, recorded_at DESC);
CREATE TRIGGER finalist_consents_append_only
    BEFORE UPDATE OR DELETE ON finalist_consents
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- Ratings entered by people for finalists who declined AI processing.
ALTER TABLE criterion_assessments
    ADD COLUMN source TEXT NOT NULL DEFAULT 'ai' CHECK (source IN ('ai', 'human'));
-- Finalists an assessment run did not rate with AI, and why.
ALTER TABLE assessment_runs ADD COLUMN skipped JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Retention (s.18): data for the category is destroyed after this date.
ALTER TABLE award_categories ADD COLUMN retention_until DATE;

-- The only way past the immutability rules: an audited purge sets wob.purge for its own
-- transaction (SET LOCAL). These rules protect against application error; a database owner
-- could always drop them, so this adds no new power, only a deliberate, logged path.
CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF current_setting('wob.purge', true) = 'on' THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION '% on % is not permitted: rows are append-only', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$;

CREATE OR REPLACE FUNCTION guard_closed_calibration() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    study_status TEXT;
BEGIN
    IF current_setting('wob.purge', true) = 'on' THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
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

-- TRUNCATE stays forbidden on the audit log even during a purge (statement-level trigger).
CREATE OR REPLACE FUNCTION forbid_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'TRUNCATE on % is not permitted: rows are append-only', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$;
DROP TRIGGER audit_events_no_truncate ON audit_events;
CREATE TRIGGER audit_events_no_truncate
    BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate();
