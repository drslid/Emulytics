-- Keep the existing public row contracts and active inventory after an application rollback.
-- Foreign keys to these tables follow the rename and continue to preserve historical records.
ALTER TABLE devices RENAME TO device_records;
ALTER TABLE device_records ADD COLUMN deleted_at timestamptz;
ALTER TABLE device_records DROP CONSTRAINT devices_host_id_serial_key;
CREATE UNIQUE INDEX devices_registered_host_serial_idx ON device_records(host_id,serial) WHERE deleted_at IS NULL;
CREATE VIEW devices AS
    SELECT device_id,host_id,serial,kind,status,created_at,display_name
    FROM device_records WHERE deleted_at IS NULL;

ALTER TABLE managed_emulators RENAME TO managed_emulator_records;
ALTER TABLE managed_emulator_records ADD COLUMN deleted_at timestamptz;
ALTER TABLE managed_emulator_records DROP CONSTRAINT managed_emulators_host_id_slot_key;
CREATE UNIQUE INDEX managed_emulators_registered_slot_idx ON managed_emulator_records(host_id,slot) WHERE deleted_at IS NULL;
CREATE VIEW managed_emulators AS
    SELECT id,device_id,host_id,slot,state,application_ids,installed_packages,last_error,last_run_id,
           create_key,create_hash,created_by,updated_at,hardware,applied_hardware
    FROM managed_emulator_records WHERE deleted_at IS NULL;

-- A prior API release must not enqueue Android work for a retired registration after rollback.
CREATE FUNCTION require_registered_execution_device() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM devices WHERE device_id=NEW.device_id FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE foreign_key_violation USING MESSAGE='Execution device is not registered';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER execution_requires_registered_device
    BEFORE INSERT ON executions FOR EACH ROW EXECUTE FUNCTION require_registered_execution_device();
