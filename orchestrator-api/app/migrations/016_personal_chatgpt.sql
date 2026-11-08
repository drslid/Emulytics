CREATE TABLE chatgpt_login_attempts (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    idempotency_key uuid NOT NULL,
    runner_id uuid NOT NULL,
    session_hash text NOT NULL,
    status text NOT NULL CHECK (status IN ('starting','pending','connected','cancelled','expired','error')),
    user_code text,
    verification_url text,
    expires_at timestamptz NOT NULL,
    lease_expires_at timestamptz NOT NULL,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(user_id,idempotency_key)
);
CREATE INDEX chatgpt_login_pending_idx ON chatgpt_login_attempts(expires_at,lease_expires_at)
    WHERE status IN ('starting','pending');
CREATE TABLE chatgpt_connections (
    user_id uuid PRIMARY KEY REFERENCES auth_users(id) ON DELETE CASCADE,
    current_attempt_id uuid REFERENCES chatgpt_login_attempts(id) ON DELETE SET NULL,
    credentials_ciphertext text,
    email text,
    plan_type text,
    connected_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
