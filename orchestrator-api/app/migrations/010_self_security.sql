CREATE TABLE auth_pending_totp (
    user_id uuid PRIMARY KEY REFERENCES auth_users(id) ON DELETE CASCADE,
    session_hash text NOT NULL REFERENCES auth_sessions(token_hash) ON DELETE CASCADE,
    secret text NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX auth_pending_totp_expiry_idx ON auth_pending_totp(expires_at);
