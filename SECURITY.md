# Security policy

Emulytics is alpha software. The supported configuration is the maintained Docker Compose console installed with `scripts/install.sh`. Security fixes target the current `main` branch. Test upgrades on infrastructure you control and keep backups of the database, Android volumes and the private encryption key.

## Report a vulnerability privately

Use [GitHub private vulnerability reporting](https://github.com/drslid/Emulytics/security/advisories/new). Include the affected revision, deployment configuration, impact and a minimal reproduction using test data. Do not open a public issue containing an exploit, personal information, passwords, TOTP seeds, recovery codes, cookies, API keys or ChatGPT credentials.

If private reporting is unavailable, open an issue asking for a private reporting channel without disclosing the vulnerability or credentials. No response deadline or paid bounty is promised.

## Deployment boundaries

- The console binds to `127.0.0.1:3100` by default. Use an SSH tunnel for remote administration, or a reviewed HTTPS reverse proxy with the correct public origin and secure cookies. Do not expose PostgreSQL, ADB or the Docker socket.
- Password authentication and TOTP are required for the supported console. An explicitly disabled authentication mode exists for isolated tests and must not be used for a shared installation.
- Admin, Builder, Operator, Viewer and Auditor permissions protect operations. This is a shared fleet with role-based access, not an isolation boundary between mutually untrusted tenants.
- The Android worker controls device data and has access to Docker. Access to its host and socket is privileged. Use devices, APKs and infrastructure that you are authorized to manage.
- Personal API keys are scoped and revocable. Personal ChatGPT credentials are owner-bound and encrypted at rest. The database and `EMULYTIX_AUTH_KEY` must be protected together; losing the key can make encrypted data unrecoverable.
- `.env.console`, initial-access files, uploaded APKs, Android data, screenshots, logs and browser sessions belong outside version control and the public documentation site.

## Release checks

CI checks the application, hashed Python dependency lock, npm locks, Go vulnerabilities and Git history for secrets. GitHub Pages publishes only the separately built `docs-site/dist` artifact. One exact historic Gitleaks fingerprint is ignored because it is a public UUID in an idempotency test, not a credential.

Audits describe the code and advisory databases available when they run. They do not guarantee the absence of vulnerabilities, certify third-party APKs, or establish the security of an Android system image, host, reverse proxy or physical device.
