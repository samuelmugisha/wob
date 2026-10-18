-- Report provenance (FR-11, FR-12).
ALTER TABLE reports
    ADD COLUMN generator_version TEXT,
    ADD COLUMN size_bytes BIGINT CHECK (size_bytes >= 0);
CREATE INDEX idx_reports_category ON reports (category_id, created_at DESC);
