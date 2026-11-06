CREATE TABLE applications (
    id uuid PRIMARY KEY,
    filename text UNIQUE NOT NULL,
    sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    package_name text NOT NULL CHECK (package_name ~ '^[A-Za-z][A-Za-z0-9_.]{1,199}$'),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 160),
    size_bytes bigint NOT NULL CHECK (size_bytes BETWEEN 1 AND 134217728),
    created_by uuid REFERENCES auth_users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX applications_package_created_idx ON applications(package_name,created_at DESC,id DESC);

CREATE TABLE managed_emulators (
    id uuid PRIMARY KEY,
    device_id text UNIQUE NOT NULL REFERENCES devices(device_id),
    host_id text NOT NULL,
    slot smallint NOT NULL CHECK (slot BETWEEN 1 AND 4),
    state text NOT NULL DEFAULT 'created' CHECK (state IN ('created','starting','ready','stopped','preparing','failed','unknown')),
    application_ids jsonb NOT NULL CHECK (jsonb_typeof(application_ids)='array' AND jsonb_array_length(application_ids)<=12),
    installed_packages jsonb NOT NULL DEFAULT '[]'::jsonb,
    last_error text,
    last_run_id uuid REFERENCES runs(id) ON DELETE SET NULL,
    create_key text UNIQUE NOT NULL,
    create_hash text NOT NULL,
    created_by uuid REFERENCES auth_users(id) ON DELETE SET NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(host_id,slot)
);

CREATE TABLE emulator_operations (
    run_id uuid PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    device_id text NOT NULL REFERENCES managed_emulators(device_id),
    action text NOT NULL CHECK (action IN ('start','prepare','stop')),
    applications jsonb NOT NULL CHECK (jsonb_typeof(applications)='array'),
    created_by uuid REFERENCES auth_users(id) ON DELETE SET NULL,
    service_actor boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX emulator_operations_device_idx ON emulator_operations(device_id,created_at DESC);
