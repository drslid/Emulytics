# Release notes in the update dialog

- [x] Return the latest stable version and its bounded GitHub release body from `GET /console/updates`. Verify that the body stays paired with its version in the cache and that missing notes do not affect release detection.
- [x] Show those notes inside the installation confirmation before the restart. Keep the version fixed while the dialog is open, offer the GitHub page, and cover safe rendering and the empty-notes state.
- [x] Use the matching `CHANGELOG.md` section when publishing a stable release. Check explicit notes and generated fallback without changing the verified commit or tag. Backfill the existing `v0.1.2` notes and prepare `v0.1.3`.
