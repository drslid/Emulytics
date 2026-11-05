ALTER TABLE executions
    ADD COLUMN lease_epoch bigint,
    ADD COLUMN started_at timestamptz,
    ADD COLUMN finished_at timestamptz,
    ADD COLUMN error text,
    ADD COLUMN evidence jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE device_leases (
    device_id text PRIMARY KEY REFERENCES devices (device_id),
    lease_epoch bigint NOT NULL DEFAULT 0 CHECK (lease_epoch >= 0),
    owner_id text,
    execution_id uuid UNIQUE REFERENCES executions (id),
    expires_at timestamptz,
    quarantined boolean NOT NULL DEFAULT false,
    CHECK (
        (owner_id IS NULL AND execution_id IS NULL AND expires_at IS NULL) OR
        (owner_id IS NOT NULL AND execution_id IS NOT NULL AND expires_at IS NOT NULL)
    )
);

CREATE TABLE action_journal (
    id uuid PRIMARY KEY,
    execution_id uuid NOT NULL REFERENCES executions (id),
    step_id text NOT NULL,
    lease_epoch bigint NOT NULL,
    action jsonb NOT NULL,
    non_idempotent boolean NOT NULL,
    status text NOT NULL DEFAULT 'intent'
        CHECK (status IN ('intent', 'done', 'failed', 'cancelled', 'uncertain')),
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz
);
CREATE INDEX executions_queue_idx ON executions (created_at, id) WHERE status = 'queued';
CREATE INDEX action_journal_execution_idx ON action_journal (execution_id, started_at);
CREATE INDEX device_leases_expiry_idx ON device_leases (expires_at) WHERE owner_id IS NOT NULL;
