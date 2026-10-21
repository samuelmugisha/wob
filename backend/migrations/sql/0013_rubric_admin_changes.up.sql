-- Administrators may unfreeze a rubric (frozen -> approved) and amend an approved rubric.
-- Both stay blocked unless the application sets wob.rubric_admin for its own transaction
-- (SET LOCAL), which it does only for an administrator's audited request. Frozen criteria
-- still never change: a rubric must be unfrozen first.

CREATE OR REPLACE FUNCTION guard_rubric_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    admin_change BOOLEAN := coalesce(current_setting('wob.rubric_admin', true), '') = 'on';
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'rubric versions must be created as drafts'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'frozen' THEN
        IF NOT (TG_OP = 'UPDATE' AND admin_change AND NEW.status = 'approved') THEN
            RAISE EXCEPTION 'rubric version % is frozen', OLD.id USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'only draft rubric versions can be deleted'
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN OLD;
    END IF;

    IF NEW.status = 'frozen' THEN
        IF NOT EXISTS (SELECT 1 FROM rubric_criteria WHERE rubric_version_id = NEW.id) THEN
            RAISE EXCEPTION 'rubric version % has no criteria', NEW.id
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.weighting = 'weighted' AND EXISTS (
            SELECT 1 FROM rubric_criteria WHERE rubric_version_id = NEW.id AND weight IS NULL
        ) THEN
            RAISE EXCEPTION 'weighted rubric version % has criteria without weights', NEW.id
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION guard_rubric_criteria() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    admin_change BOOLEAN := coalesce(current_setting('wob.rubric_admin', true), '') = 'on';
    parent rubric_status;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT status INTO parent FROM rubric_versions WHERE id = OLD.rubric_version_id;
        IF NOT (parent = 'draft' OR (parent = 'approved' AND admin_change)) THEN
            RAISE EXCEPTION 'criteria of non-draft rubric version % cannot change', OLD.rubric_version_id
                USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT status INTO parent FROM rubric_versions WHERE id = NEW.rubric_version_id;
        IF NOT (parent = 'draft' OR (parent = 'approved' AND admin_change)) THEN
            RAISE EXCEPTION 'criteria of non-draft rubric version % cannot change', NEW.rubric_version_id
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    RETURN OLD;
END
$$;
