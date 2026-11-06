ALTER TABLE auth_users
    ADD COLUMN password_change_required boolean NOT NULL DEFAULT false;

ALTER TABLE auth_challenges DROP CONSTRAINT auth_challenges_purpose_check;
ALTER TABLE auth_challenges ADD CONSTRAINT auth_challenges_purpose_check
    CHECK (purpose IN ('change_password', 'enroll', 'verify'));

CREATE TABLE auth_installation (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    bootstrapped boolean NOT NULL DEFAULT false
);
INSERT INTO auth_installation(singleton, bootstrapped)
    VALUES (true, EXISTS(SELECT 1 FROM auth_users));
