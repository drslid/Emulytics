CREATE TABLE run_retries (
 source_run_id uuid NOT NULL REFERENCES runs(id),
 retry_run_id uuid NOT NULL UNIQUE REFERENCES runs(id),
 request_id uuid PRIMARY KEY, actor_id uuid REFERENCES auth_users(id) ON DELETE SET NULL,
 request_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX run_retries_source_idx ON run_retries(source_run_id);
