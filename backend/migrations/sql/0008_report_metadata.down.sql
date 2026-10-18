DROP INDEX IF EXISTS idx_reports_category;
ALTER TABLE reports DROP COLUMN size_bytes, DROP COLUMN generator_version;
