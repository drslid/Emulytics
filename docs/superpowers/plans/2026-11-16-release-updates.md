# GitHub releases and self-hosted updates

**Goal** — Publish one stable GitHub release for each version that passes CI. Let a console administrator see and install the latest compatible release on a managed host.

## Contracts

- `VERSION` contains the stable application version in `X.Y.Z` format. The initial version is `0.1.0`, matching the console package. The release tag is `vX.Y.Z`; Android runtime image versions are independent.
- On a successful main-branch push, `.github/workflows/ci.yml` checks whether the version already has a stable release and publishes it from the exact tested commit if needed.
- `GET /console/updates` reports installed and latest stable versions, release URL, availability, installation readiness, update state, target version, a bounded error code and release-check failures. `POST /console/updates` accepts the displayed version only. Both require a personal admin session with `updates.manage`.
- `/updates/requests/request.json` is the single handoff from the API to the host. It contains the stable version and a UUID. The host atomically writes a status file into `/updates/status`, which the API mounts read-only.
- The local runner rechecks the canonical GitHub release and matches the tagged commit to its release SHA. It prepares images in an isolated worktree, then activates with the same Compose project. It refuses active executions and holds a PostgreSQL advisory lock to keep queued executions from starting while the local services restart. The release process preserves `.env.console`, PostgreSQL, Android data and the local source branch.
- The durable host journal records the original revision and the prepare, activate and restore phases. Recovery consults it before the writable inbox, including after an interrupted rollback. Database migrations must remain compatible with the previous stable application during recovery.

## Tasks

- [x] Add and test the release command, the unchanged-version no-op and older or mismatched tag rejection. Use `VERSION`, `.github/workflows/ci.yml` and `CONTRIBUTING.md`.
- [x] Implement host setup and apply in `scripts/update.py`, `scripts/install.py`, `scripts/start-console.sh` and `docker-compose.preview.yml`. Cover request validation, overlapping attempts, exact release, restart and failed deployment.
- [x] Add the update endpoints and tests in `orchestrator-api/app/update_routes.py`, `orchestrator-api/app/access.py`, `orchestrator-api/app/main.py` and `orchestrator-api/tests/test_release_updates.py`. Check authorization, stable version comparison, network failures, repeat and competing requests.
- [x] Add an admin-only update notice and Settings action in the web console, including the control proxy and ten existing language catalogs. Verify the waiting and restart states in the browser and build the frontend.
- [x] Document one-time setup for existing installations, version publishing and update behavior in the README and GitHub Pages guides.

## Additional console requests

- [x] Make store search primary in the Desired applications picker and display a compact list of selected apps. Keep the existing stored application limit and saved configurations. Changes live in `web-ui/components/console/emulators.tsx`, `web-ui/components/console/apk-store-picker.tsx`, `web-ui/lib/emulators.ts` and `web-ui/app/emulators.css`.
- [x] Add Aptoide alongside F-Droid. Search apps by name or package, retrieve versions only for the chosen app, and return an exact asset identifier. Verify bounded downloads, package/version, Android 10 x86 compatibility, and the APK signing certificate before publishing. The backend is `orchestrator-api/app/aptoide_catalog.py`, `orchestrator-api/app/apk_catalog.py`, and `orchestrator-api/app/emulator_routes.py`. Update the devices guide and the demo screenshot. The LinkedIn native APK and the Snapchat Web APK passed inspection using AAPT and `apksigner`.
- [x] Let installation administrators set the shared default provider, encrypted DeepSeek key and model, and Ollama endpoint and model in Settings. Preserve environment defaults, per-user OpenAI connection, and the per-draft override. Use `/console/account/ai-providers` and the existing recipe endpoints. Verify shared settings, admin-only edits, secret redaction, and validation.
