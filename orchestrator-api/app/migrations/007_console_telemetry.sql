ALTER TABLE devices ADD COLUMN display_name text NOT NULL DEFAULT '';
UPDATE devices SET display_name = device_id;
CREATE TABLE service_heartbeats (
 component text NOT NULL, instance_id text NOT NULL, host_id text,
 status text NOT NULL, metrics jsonb NOT NULL DEFAULT '{}',
 last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(component, instance_id)
);
CREATE INDEX service_heartbeats_recent_idx ON service_heartbeats(last_seen_at DESC);
