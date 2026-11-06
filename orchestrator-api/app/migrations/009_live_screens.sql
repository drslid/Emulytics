CREATE TABLE live_screen_requests (
    device_id text PRIMARY KEY REFERENCES devices(device_id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL
);
CREATE INDEX live_screen_requests_expiry_idx ON live_screen_requests(expires_at);
