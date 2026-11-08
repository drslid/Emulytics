CREATE TABLE device_groups (
 id uuid PRIMARY KEY, name text NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
 revision integer NOT NULL DEFAULT 1 CHECK(revision>0),
 created_by uuid REFERENCES auth_users(id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE UNIQUE INDEX device_groups_name_idx ON device_groups(lower(name));
CREATE TABLE device_group_members (
 group_id uuid NOT NULL REFERENCES device_groups(id) ON DELETE CASCADE,
 device_id text NOT NULL REFERENCES devices(device_id), PRIMARY KEY(group_id,device_id)
);
CREATE TABLE fleet_bulk_requests (
 request_id uuid PRIMARY KEY, actor_id uuid REFERENCES auth_users(id) ON DELETE SET NULL,
 request_hash text NOT NULL, action text NOT NULL CHECK(action IN ('start','prepare','stop')),
 results jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
