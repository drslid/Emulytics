CREATE TABLE personal_api_keys (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    request_id uuid NOT NULL,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    token_hash text NOT NULL UNIQUE,
    token_prefix text NOT NULL,
    scopes text[] NOT NULL CHECK (cardinality(scopes) BETWEEN 1 AND 6),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    expires_at timestamptz NOT NULL,
    last_used_at timestamptz,
    revoked_at timestamptz,
    UNIQUE(user_id,request_id)
);
CREATE INDEX personal_api_keys_owner_idx ON personal_api_keys(user_id,created_at DESC);
CREATE TABLE personal_api_run_requests (
    user_id uuid NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    client_key_hash text NOT NULL,
    run_id uuid NOT NULL UNIQUE REFERENCES runs(id),
    request_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(user_id,client_key_hash)
);

-- Account changes must not revive an old key when an account is enabled again.
CREATE FUNCTION revoke_personal_keys_after_access_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE personal_api_keys SET revoked_at=clock_timestamp()
        WHERE user_id=NEW.id AND revoked_at IS NULL;
    RETURN NEW;
END;
$$;
CREATE TRIGGER personal_api_keys_access_change AFTER UPDATE ON auth_users
    FOR EACH ROW WHEN (
        OLD.role IS DISTINCT FROM NEW.role OR OLD.active IS DISTINCT FROM NEW.active OR
        OLD.password_hash IS DISTINCT FROM NEW.password_hash OR
        OLD.password_change_required IS DISTINCT FROM NEW.password_change_required OR
        OLD.totp_enabled IS DISTINCT FROM NEW.totp_enabled OR OLD.totp_secret IS DISTINCT FROM NEW.totp_secret
    ) EXECUTE FUNCTION revoke_personal_keys_after_access_change();
