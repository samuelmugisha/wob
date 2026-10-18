DROP TABLE IF EXISTS
    audit_events, reports, ranking_entries, ranking_snapshots, assessment_citations,
    criterion_assessments, assessment_runs, verification_reviews, claim_evidence,
    external_sources, claims, document_chunks, documents, imports, finalist_categories,
    finalists, rubric_criteria, rubric_versions, award_categories, rating_scale, users;

DROP FUNCTION IF EXISTS
    forbid_mutation(), guard_rubric_version(), guard_rubric_criteria(),
    protect_document_original(), require_confirmed_mapping();

DROP TYPE IF EXISTS
    user_role, rubric_status, weighting_mode, job_status, processing_status, source_type,
    claim_status, evidence_relation, quality_level, review_outcome, evidence_sufficiency,
    assessment_status, report_kind;
