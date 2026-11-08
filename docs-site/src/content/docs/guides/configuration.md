---
title: Configuration and ChatGPT
description: Connect a personal ChatGPT account for supported free-form journey generation.
---

**Settings** contains the personal ChatGPT connection and links to configuration areas appropriate to your role. Passwords and second factors remain under **My profile**.

## Connect ChatGPT

1. Choose the connection action in Settings.
2. Open the official URL supplied by the device-code flow.
3. Sign in with your ChatGPT account and enter the displayed device code.
4. Return to the console and wait for confirmation.

Opening the provider page alone does not establish the connection. A pending code expires or can be canceled. You can disconnect your account from the installation later.

ChatGPT is the only external account offered. Each connection belongs to one local user; it is not a shared worker identity. The server uses an isolated official Codex process and encrypted storage. It does not borrow the developer workstation's Codex account.

## What the connection enables

The local Wikipedia and Android-version reference goals do not require an external account. Other supported natural-language goals use the connected user's credentials to request a draft plan.

The planning process has no shell, file, browser or MCP tools. Its output is checked against the typed journey contract and Android driver's allowlist. A model response does not authorize arbitrary commands or unsupported application behavior.

The generated draft still needs review, publication and a device test. A valid connection does not mean every natural-language objective can be executed.

## Deployment settings

Configuration variables retain the `EMULYTIX_` prefix. The installer creates a private `.env.console`. Keep its encryption key and database credentials with the installation's backup.

For remote console access, terminate HTTPS at a trusted reverse proxy, set `EMULYTIX_PUBLIC_ORIGIN` to the exact public origin and enable secure cookies. The default port remains bound to loopback.

The device-code integration targets the local, self-hosted application. A commercial hosted service would need a separate review of the provider's supported authentication integration. End-to-end generation with an authorized personal ChatGPT account remains a distinct validation from the local reference journeys.
