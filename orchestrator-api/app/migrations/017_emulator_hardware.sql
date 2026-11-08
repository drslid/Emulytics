ALTER TABLE managed_emulators
    ADD COLUMN hardware jsonb NOT NULL DEFAULT '{"width":720,"height":1280,"density":320,"ram_mb":1536,"cpu_cores":2,"storage_gb":8}'::jsonb
        CHECK (jsonb_typeof(hardware)='object'),
    ADD COLUMN applied_hardware jsonb CHECK (applied_hardware IS NULL OR jsonb_typeof(applied_hardware)='object');
