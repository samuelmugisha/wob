-- External research by award criterion (FR-13): public evidence found for a rubric criterion
-- rather than for an extracted claim, so finalists without uploaded documents can be researched.

-- The criterion is recorded by code and name as they stood at research time: rubric drafts
-- replace their criteria on edit, so a foreign key would not survive.
ALTER TABLE external_sources
    ADD COLUMN criterion_code TEXT,
    ADD COLUMN criterion_name TEXT,
    ADD CONSTRAINT external_sources_one_subject CHECK (
        claim_id IS NULL OR criterion_code IS NULL
    ),
    ADD CONSTRAINT external_sources_criterion_named CHECK (
        (criterion_code IS NULL) = (criterion_name IS NULL)
    );

ALTER TABLE research_runs ADD COLUMN criterion_codes TEXT[] NOT NULL DEFAULT '{}';
