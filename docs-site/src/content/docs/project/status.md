---
title: Status and scope
description: Know what is implemented, what has been validated and what remains planned.
---

Emulytics is an early self-hosted release. The repository combines implemented console features with an explicit roadmap; a planned feature is not a shipped platform guarantee.

## Available now

- Local password and mandatory TOTP authentication with five roles.
- Managed persistent Android emulators, hardware profiles and verified APK preparation.
- Existing Android-device registration, selected groups and managed-device bulk actions.
- Natural-language reference journeys, validated drafts and immutable publication versions.
- Immediate launches, timezone-aware CRON scheduling and PostgreSQL-backed queue/leases.
- Active live screens, step captures, observed Android-version results and controlled retries.
- Published-version removal with retained execution history.
- Dashboard charts, observed architecture flows, monitoring and audit views.
- Scoped personal REST keys and a stdio MCP adapter.
- A single-command install entry point after cloning and meeting host prerequisites.

## Current limits

| Area | Current scope |
|---|---|
| Local emulator | Android 10 / API 29, x86_64, provided system-image Chrome |
| Installation | Linux x86_64, local Docker Engine/Compose and KVM |
| Other mobile platforms | iOS is planned, not implemented |
| Natural-language generation | Bounded driver capabilities, not universal app automation |
| Social applications | APK preparation entries exist; arbitrary social workflows are not verified |
| Application distribution | Standalone APKs from F-Droid, Aptoide or uploads. Store releases must support Android 10 x86 |
| Existing Android storage | Preserved volumes; no supported resizing after initialization |
| Workspace model | Role-based shared workspace, not customer tenancy |
| Parallelism | One active journey per worker process and one per device; host capacity still matters |
| Go migration | Selected reads only; Python remains part of the control plane |
| AI providers | Local reference goals use templates. Live OpenAI, Ollama and DeepSeek connections require provider-specific validation |

Local regressions use disposable databases and controlled browser checks. They do not establish a large-fleet benchmark, broad OEM compatibility, physical-phone certification, complete backup/restore validation or universal third-party app compatibility.

Read [installation](/Emulytics/getting-started/install/) and the [security model](/Emulytics/reference/security/) before deployment. GitHub Pages hosts documentation only; it is not an online instance of the console.
