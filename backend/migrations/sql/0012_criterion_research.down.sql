ALTER TABLE research_runs DROP COLUMN criterion_codes;
ALTER TABLE external_sources
    DROP CONSTRAINT external_sources_criterion_named,
    DROP CONSTRAINT external_sources_one_subject,
    DROP COLUMN criterion_name,
    DROP COLUMN criterion_code;
