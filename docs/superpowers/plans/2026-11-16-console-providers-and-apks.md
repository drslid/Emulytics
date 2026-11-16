---
title: Console providers and APK search
tags:
  - emulytics
  - implementation-plan
---

# Console Providers and APK Search Implementation Plan

**Goal** — Configure OpenAI, Ollama, and DeepSeek for draft generation, let device managers import a selected F-Droid release, and document both workflows with console screenshots.

**Architecture** — Extend the existing authenticated recipe generation and emulator catalog endpoints. Keep credentials and F-Droid downloads on the orchestrator. Reuse the existing app catalog, emulator preparation operation, and GitHub Pages build.

**Head** — `6e34e57` on `main`.

## Contracts

- `POST /console/recipes/generate` accepts `instructions` and optional `provider` (`openai`, `ollama`, or `deepseek`). Omitted provider uses the existing OpenAI flow. Known local goals still return `verified_template`. Other goals require an authenticated user with `workflows.write`. `GET /console/recipes/providers` returns only configured model names for Ollama and DeepSeek. Ollama receives instructions on the local service. DeepSeek receives instructions over HTTPS using the server's key. Generation returns a validated draft without sending Android device data or running actions.
- `GET /console/applications/fdroid?q=…` returns `items` containing `package_name`, `name`, and `versions`. Each release has `sha256`, `version_name`, `version_code`, `added_at` in UTC, and `size_bytes`. `POST` on the same route accepts only `package_name` and `sha256` and returns the saved emulator application. Browser requests require `devices.write` and the existing console authentication. Direct control API calls require the installation's bearer control token.
- Load the F-Droid main catalog on demand and retain its compatible standalone APKs for Android 10. Validate release size, hash, package and version before publication. Keep the exact imported UUID in the existing emulator configuration format. A repeated import of the same verified package and digest reuses its stored APK.

## Files by workflow

- Provider implementation in `orchestrator-api/app/automation_models.py`, `orchestrator-api/app/automation_routes.py`, `orchestrator-api/app/journey_provider.py`, `.env.example`, `docker-compose.preview.yml`, `web-ui/components/console/configuration.tsx`, `web-ui/components/console/chatgpt-connection.tsx`, `web-ui/components/console/recipe-editor.tsx`, and `web-ui/app/configuration.css`. Provider checks in `orchestrator-api/tests/test_external_journey_providers.py`, `orchestrator-api/tests/test_android_version_goal.py`, and `web-ui/tests/client-api.test.mjs`.
- F-Droid implementation in `orchestrator-api/app/fdroid_catalog.py`, `orchestrator-api/app/emulator_routes.py`, `orchestrator-api/app/apk_catalog.py`, `orchestrator-api/app/emulator_store.py`, `orchestrator-api/requirements.txt`, `orchestrator-api/requirements.lock`, `web-ui/components/console/fdroid-picker.tsx`, `web-ui/components/console/emulators.tsx`, `web-ui/app/emulators.css`, and `web-ui/lib/emulators.ts`. APK checks in `orchestrator-api/tests/test_fdroid_catalog.py`, `orchestrator-api/tests/test_managed_emulators.py`, and `web-ui/tests/emulators.test.mjs`.
- Shared authorization, types, and translations in `orchestrator-api/app/access.py`, `web-ui/lib/client-api.ts`, `web-ui/lib/console-types.ts`, `web-ui/lib/control-proxy.ts`, and the ten catalogs in `web-ui/lib/locales/`. Proxy checks live in `web-ui/tests/control-proxy.test.mjs`.
- Documentation in `README.md`, `docs/configuration-chatgpt.md`, `docs-site/README.md`, `docs-site/astro.config.mjs`, and the Devices, Configuration, Journeys, first-journey, overview, status and troubleshooting pages under `docs-site/src/content/docs/`. Screenshots are `docs-site/public/brand/console/dashboard.png`, `docs-site/public/brand/console/apk-search.png`, and `docs-site/public/brand/console/settings.png`.

## Recipe generation

- [x] Verify the no-account path in `app/automation_routes.py` and `app/journey_provider.py` and document the deterministic templates and manual editing path.
- [x] Extend `automation_models.py`, `automation_routes.py`, and `journey_provider.py` with provider selection. Retain the existing request default and draft validation. Expose configured providers and model names through `GET /console/recipes/providers`.
- [x] Update Settings and the recipe editor to identify OpenAI, expose the available provider choices, and explain local Ollama and DeepSeek setup. Pass the new read route through `web-ui/lib/control-proxy.ts`.
- [x] Verify omitted provider retains the OpenAI path, recognized goals retain their templates, and Ollama and DeepSeek send the expected payloads through their separate endpoints. Reject unconfigured providers and malformed responses. Check that Settings renders the configured model names and type-check and build the production console.

## Desired applications

- [x] Add authenticated F-Droid search and release import in `orchestrator-api/app/emulator_routes.py` and `fdroid_catalog.py`. Search by name or package and return the APK version, version code, catalog date, and digest. Download the selected digest from the fixed F-Droid origin, verify the APK, then publish through the existing catalog.
- [x] Pass `GET` and `POST /console/applications/fdroid` through the Next.js control proxy. In `components/console/emulators.tsx`, add an inline search with loading, no results, error, release selection and import states. Keep the imported release selected by its catalog ID and support switching versions of a selected package within the twelve-app limit.
- [x] Check the rendered picker at desktop and mobile widths. Confirm the local APK upload retains the original catalog behavior and the emulator keeps the exact selected release ID. Verify unauthorized access, digest and manifest mismatches, transfer deadlines, and repeat imports. Inspect a real downloaded F-Droid APK with `aapt`.

## Documentation

- [x] Update `README.md`, the Settings and Devices guides, and other affected GitHub Pages instructions. Explain that APK preparation happens after import and emulator creation.
- [x] Capture the rendered console with demonstration data and reference the shared screenshots from the README and the relevant guides.
- [x] Run the frontend tests and Pages production build. Check that the screenshots load under the `/Emulytics/` base path and stay within a 390 px viewport.

## Project workflows

- Using Superpowers and Writing Plans shaped the implementation sequence. APEX supplied the preflight, execution and verification stages. Grilling narrowed the remaining store choice after the repository and catalog were checked.
- Graphify traced the settings, generation and emulator paths. Ponytail guided reuse of the proxy, upload, catalog and draft validation code.
- Impeccable and Make Interfaces Feel Better guided the inline picker, loading states, focus and responsive checks.
- Elephant-Goldfish and the thermo-nuclear code quality review independently checked authorization, provider boundaries, download deadlines and exact-release reuse.
- Pipeline Blueprint guided the Pages build verification. Obsidian Markdown guidance is reflected in the plan's frontmatter and Markdown structure.

## Verification still requiring a running installation

- Authenticate through OpenAI and run a free-form request on configured Ollama and DeepSeek instances. Provider request and response handling was exercised with simulated responses.
- Run the Docker-backed PostgreSQL tests and install an imported APK on Android. Local verification covered the live F-Droid download, matching digest and manifest, and the rendered selection flow.
