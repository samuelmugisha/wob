-- Authentication (spec §9 bearer auth, §12 access control): invited accounts, hashed
-- passwords, optional TOTP, revocable sessions.

ALTER TABLE users
    ADD COLUMN password_hash TEXT,
    ADD COLUMN password_set_at TIMESTAMPTZ,
    ADD COLUMN failed_logins INTEGER NOT NULL DEFAULT 0 CHECK (failed_logins >= 0),
    ADD COLUMN locked_until TIMESTAMPTZ,
    ADD COLUMN last_login_at TIMESTAMPTZ,
    -- TOTP secret, encrypted with the application key (never stored in clear).
    ADD COLUMN mfa_secret_encrypted TEXT,
    ADD COLUMN mfa_enabled BOOLEAN NOT NULL DEFAULT false,
    ADD CONSTRAINT users_mfa_needs_secret CHECK (NOT mfa_enabled OR mfa_secret_encrypted IS NOT NULL);

-- Only hashes of tokens are stored: a database leak does not leak usable sessions or invites.
CREATE TABLE user_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id),
    token_hash CHAR(64) NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'browser' CHECK (kind IN ('browser', 'api')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    ip_address TEXT,
    user_agent TEXT
);
CREATE INDEX idx_user_sessions_user ON user_sessions (user_id) WHERE revoked_at IS NULL;

CREATE TABLE user_invites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id),
    token_hash CHAR(64) NOT NULL UNIQUE,
    created_by UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX idx_user_invites_user ON user_invites (user_id);
