CREATE TABLE automation_recipes (
    id uuid PRIMARY KEY,
    workflow_id text UNIQUE NOT NULL,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    instructions text NOT NULL,
    definition jsonb NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    published_revision integer,
    latest_version integer,
    created_by uuid REFERENCES auth_users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE automation_schedules (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    workflow_id text NOT NULL,
    workflow_version integer NOT NULL,
    device_ids jsonb NOT NULL CHECK (jsonb_array_length(device_ids) BETWEEN 1 AND 100),
    max_concurrency integer NOT NULL CHECK (max_concurrency BETWEEN 1 AND jsonb_array_length(device_ids)),
    cron text NOT NULL,
    timezone text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    created_by uuid REFERENCES auth_users(id) ON DELETE SET NULL,
    next_run_at timestamptz NOT NULL,
    last_run_id uuid REFERENCES runs(id),
    last_error text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (workflow_id, workflow_version) REFERENCES workflows(workflow_id, version)
);
CREATE INDEX automation_schedules_due_idx ON automation_schedules(next_run_at) WHERE enabled;
