---
title: Security model
description: Understand account, network, worker and artifact trust boundaries.
---

## Deployment boundary

Emulytics is a self-hosted shared-workspace application. Operate it on infrastructure and devices you control. The default console listens on loopback; remote access requires your own HTTPS reverse proxy and exact origin configuration.

The Android worker can manage owned emulator containers through Docker. Treat the host, Docker daemon, worker code and operators with host access as trusted. The worker is not a sandbox for hostile plug-ins or arbitrary shell programs.

## Accounts and authorization

- Passwords are hashed with Argon2; temporary access must be replaced.
- TOTP is mandatory; enrolled secrets and personal provider credentials are encrypted.
- Sessions, recovery codes and personal API secrets are represented by non-recoverable fingerprints where applicable.
- HttpOnly, SameSite cookies and exact-origin checks protect console requests. Insecure cookies are limited to the configured local HTTP origin.
- Server-side role checks apply independently of hidden or visible buttons.
- Shared database-backed limits protect authentication and personal API use across processes.

Five roles control actions in one workspace. The product does not claim customer-tenant isolation.

## Android input and artifacts

Driver actions use validated arguments and fixed command families. Generated plans cannot supply arbitrary shell commands, arbitrary system properties, paths to private APKs or unsupported intents.

APK uploads are bounded, inspected for package identity and stored with generated names and cryptographic hashes. Application preparation verifies the selected artifact. Importing an APK does not establish that its application is trustworthy; obtain it from a source you trust.

Step captures require authentication and a valid execution relationship. Treat screenshots, Android UI hierarchies, uploaded APKs and database backups as sensitive local application data.

## Secrets and backups

Never publish `.env.console`, authentication keys, database credentials, personal API keys, ChatGPT tokens, authenticator QR codes, recovery codes or populated data volumes.

Back up the private environment file, PostgreSQL and required Android/artifact data together using a consistent operational procedure. Losing the environment's encryption key can make stored factors and provider connections unreadable. Do not remove volumes as a troubleshooting shortcut.

This documentation site contains only authored public guides and explicit public brand assets. It does not publish operational reports or local screenshots.

## Report a vulnerability

Follow the repository's [security reporting policy](https://github.com/drslid/Emulytics/blob/main/SECURITY.md). Do not put credentials, personal screenshots or a working exploit against a public instance into a public issue.

A code and dependency review is not a claim that the product is vulnerability-free. Review the current [project scope](/Emulytics/project/status/) and deployment assumptions before exposing an installation.
