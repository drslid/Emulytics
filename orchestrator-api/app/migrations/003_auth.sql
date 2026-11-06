CREATE TABLE auth_users (
    id uuid PRIMARY KEY,
    username text UNIQUE NOT NULL CHECK (username ~ '^[a-z0-9][a-z0-9_.-]{2,63}$'),
    password_hash text NOT NULL,
    totp_secret text,
    totp_enabled boolean NOT NULL DEFAULT false,
    totp_last_counter bigint NOT NULL DEFAULT -1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (NOT totp_enabled OR totp_secret IS NOT NULL)
);

CREATE TABLE auth_challenges (
    token_hash text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    purpose text NOT NULL CHECK (purpose IN ('enroll', 'verify')),
    expires_at timestamptz NOT NULL
);
CREATE INDEX auth_challenges_expiry_idx ON auth_challenges(expires_at);

CREATE TABLE auth_sessions (
    token_hash text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX auth_sessions_expiry_idx ON auth_sessions(expires_at);

CREATE TABLE auth_recovery_codes (
    user_id uuid NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    code_hash text NOT NULL,
    PRIMARY KEY (user_id, code_hash)
);

CREATE TABLE auth_rate_limits (
    bucket_key text PRIMARY KEY,
    attempts integer NOT NULL,
    window_start timestamptz NOT NULL DEFAULT clock_timestamp()
);
