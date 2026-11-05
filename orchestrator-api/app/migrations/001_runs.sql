CREATE TABLE devices (
    device_id text PRIMARY KEY,
    host_id text NOT NULL,
    serial text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('physical', 'emulator')),
    status text NOT NULL DEFAULT 'registered' CHECK (status = 'registered'),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (host_id, serial)
);

CREATE TABLE workflows (
    workflow_id text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    definition jsonb NOT NULL,
    content_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workflow_id, version)
);

CREATE TABLE runs (
    id uuid PRIMARY KEY,
    workflow_id text NOT NULL,
    workflow_version integer NOT NULL,
    device_ids jsonb NOT NULL CHECK (jsonb_array_length(device_ids) BETWEEN 1 AND 100),
    max_concurrency integer NOT NULL CHECK (max_concurrency BETWEEN 1 AND 100),
    parameters jsonb NOT NULL,
    idempotency_key text NOT NULL UNIQUE,
    request_hash text NOT NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'needs_review', 'waiting_auth')),
    cancel_requested boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (workflow_id, workflow_version) REFERENCES workflows (workflow_id, version),
    CHECK (max_concurrency <= jsonb_array_length(device_ids))
);
CREATE INDEX runs_created_at_idx ON runs (created_at DESC, id DESC);

CREATE TABLE executions (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES runs (id),
    device_id text NOT NULL REFERENCES devices (device_id),
    attempt integer NOT NULL DEFAULT 1 CHECK (attempt > 0),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'leased', 'running', 'recovering', 'verifying_state',
                          'waiting_auth', 'needs_review', 'succeeded', 'failed', 'cancelled')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, device_id, attempt)
);

CREATE TABLE run_events (
    run_id uuid NOT NULL REFERENCES runs (id),
    sequence bigint NOT NULL CHECK (sequence > 0),
    type text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, sequence)
);
