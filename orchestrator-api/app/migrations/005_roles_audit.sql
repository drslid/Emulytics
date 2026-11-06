ALTER TABLE auth_users
    ADD COLUMN display_name text NOT NULL DEFAULT '',
    ADD COLUMN role text NOT NULL DEFAULT 'admin' CHECK (role IN ('admin','builder','operator','viewer','auditor')),
    ADD COLUMN active boolean NOT NULL DEFAULT true;
UPDATE auth_users SET display_name=username WHERE display_name='';
ALTER TABLE auth_users ADD CONSTRAINT auth_users_display_name_length CHECK (length(display_name) BETWEEN 1 AND 120);

CREATE TABLE audit_log (
    id bigserial PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    actor_id uuid REFERENCES auth_users(id) ON DELETE SET NULL,
    action text NOT NULL,
    entity_id text,
    severity text NOT NULL DEFAULT 'info' CHECK (severity IN ('info','warning','error')),
    category text NOT NULL DEFAULT 'security',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX audit_log_occurred_at_idx ON audit_log(occurred_at DESC,id DESC);
CREATE INDEX audit_log_category_idx ON audit_log(category,id DESC);
