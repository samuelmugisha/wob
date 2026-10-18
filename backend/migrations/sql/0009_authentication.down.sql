DROP TABLE IF EXISTS user_invites;
DROP TABLE IF EXISTS user_sessions;
ALTER TABLE users
    DROP CONSTRAINT users_mfa_needs_secret,
    DROP COLUMN mfa_enabled,
    DROP COLUMN mfa_secret_encrypted,
    DROP COLUMN last_login_at,
    DROP COLUMN locked_until,
    DROP COLUMN failed_logins,
    DROP COLUMN password_set_at,
    DROP COLUMN password_hash;
