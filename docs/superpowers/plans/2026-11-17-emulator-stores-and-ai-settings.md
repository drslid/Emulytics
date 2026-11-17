# Emulator stores and AI settings implementation plan

**Goal** — Search three catalogues in the emulator form, offer the latest Aurora Store as a checkbox, and group AI configuration in one section.

## Emulator applications

- [x] Search F-Droid, Aptoide and APKMirror in parallel from one field. Keep results identified by source and preserve results when another source fails. Verify this in the creation form on desktop and mobile.
- [x] Expose public APKMirror metadata through `GET /console/applications/apkmirror`. Link to the official page to download a standalone APK, then use the existing upload flow. Test safe same-origin result links, bounded requests and partial failure.
- [x] Expose `POST /console/applications/aurora` to import the latest stable standalone APK from official Aurora OSS sources. Require the upstream signing certificate, use the existing APK checks and store the resulting application ID in the emulator configuration. Test artifact identity and reuse.

## Settings and publication

- [x] Place the shared default provider and the OpenAI, Ollama and DeepSeek options in one Settings section. Display status and open one provider's details at a time. Preserve the existing application-wide permissions and personal OpenAI connection.
- [x] Add `POST /console/account/ai-providers/test` for a live OpenAI credential check and for shared Ollama and DeepSeek model discovery. Verify session and role checks, server errors, timeout and a model missing from the available list. Keep provider credentials and raw errors out of the test response.
- [x] Verify the production web build and relevant API tests. Refresh the Settings and emulator screenshots, update the README and GitHub Pages guides, and bump `VERSION` for the next stable GitHub release.
