ALTER TABLE managed_emulators DROP CONSTRAINT managed_emulators_state_check;
ALTER TABLE managed_emulators ADD CONSTRAINT managed_emulators_state_check
    CHECK (state IN ('created','starting','running','ready','stopped','preparing','failed','unknown'));
