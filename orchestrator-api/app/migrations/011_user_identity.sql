ALTER TABLE auth_users
    ADD COLUMN first_name text NOT NULL DEFAULT '' CHECK (length(first_name) <= 120),
    ADD COLUMN last_name text NOT NULL DEFAULT '' CHECK (length(last_name) <= 120),
    ADD COLUMN email text CHECK (email IS NULL OR length(email) BETWEEN 3 AND 320),
    ADD COLUMN password_changed_at timestamptz,
    ADD COLUMN last_login_at timestamptz;

-- Existing password dates are unknown; only newly generated credentials get a date.
ALTER TABLE auth_users ALTER COLUMN password_changed_at SET DEFAULT clock_timestamp();
ALTER TABLE auth_users DROP CONSTRAINT auth_users_display_name_length;
ALTER TABLE auth_users ADD CONSTRAINT auth_users_display_name_length CHECK (length(display_name) BETWEEN 1 AND 241);
CREATE UNIQUE INDEX auth_users_email_lower_unique ON auth_users(lower(email)) WHERE email IS NOT NULL;
CREATE INDEX auth_sessions_user_expiry_idx ON auth_sessions(user_id,expires_at);
