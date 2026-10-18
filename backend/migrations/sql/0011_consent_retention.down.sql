DROP TRIGGER audit_events_no_truncate ON audit_events;
CREATE TRIGGER audit_events_no_truncate
    BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();
DROP FUNCTION forbid_truncate();

CREATE OR REPLACE FUNCTION guard_closed_calibration() RETURNS trigger LANGUAGE plpgsql AS $$
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

CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% on % is not permitted: rows are append-only', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$;

ALTER TABLE award_categories DROP COLUMN retention_until;
ALTER TABLE assessment_runs DROP COLUMN skipped;
ALTER TABLE criterion_assessments DROP COLUMN source;
DROP TABLE IF EXISTS finalist_consents;
