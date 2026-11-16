---
title: Settings and AI providers
description: Manage console updates and configure OpenAI, local Ollama or DeepSeek.
---

Open **Settings** to see the available AI providers and connection status. Passwords and second factors are managed under **My profile**.

![Settings showing OpenAI and the configured models for Ollama and DeepSeek](/Emulytics/brand/console/settings.png)

Settings in a demonstration workspace.

## Updates

Administrators can see the installed version, the latest stable release and the installation status under **Settings → Updates**. When a newer release is available, choose **Update** and confirm the restart. Keep the console open or return to Settings to read the result. [Set up the host updater](/Emulytics/getting-started/install/#update-emulytics).

## Connect OpenAI

1. Choose the connection action under **OpenAI** in **Settings**.
2. Open the official URL supplied by the device-code flow.
3. Sign in with your ChatGPT account and enter the displayed device code.
4. Return to the console and wait for confirmation.

Wait for confirmation in the console. A pending code expires or can be canceled. You can disconnect your account from the installation later.

Each OpenAI connection belongs to one local user. The server uses an isolated official Codex process and encrypted storage.

## Configure and activate an AI provider

In **Settings**, administrators select **OpenAI**, **DeepSeek**, or **Ollama** as the default for the installation. Users can see the default and select another available provider for a specific draft in the journey editor. Each user connects their own OpenAI account to generate journeys with OpenAI.

For **DeepSeek**, an administrator enters the shared API key and the model name. The server encrypts the key and Settings displays a saved indicator. Leave the key field blank to keep the current key. DeepSeek receives the text of the generation request over HTTPS. [DeepSeek API documentation](https://api-docs.deepseek.com/)

For **Ollama**, an administrator downloads the model with `ollama pull <model>` and enters its exact tag and the shared server URL reachable from Emulytics. For Ollama running on the Docker host, use `http://host.docker.internal:11434`. If it listens only on `127.0.0.1`, set `OLLAMA_HOST` to an address reachable from the Docker network and restart Ollama. Use a private IP address for a server on your local network. To keep inference local, set `OLLAMA_NO_CLOUD=1` on the Ollama server. [Ollama documentation](https://docs.ollama.com/)

The installer can also provide defaults through the existing `EMULYTIX_OLLAMA_URL`, `EMULYTIX_OLLAMA_MODEL`, `EMULYTIX_DEEPSEEK_API_KEY`, and `EMULYTIX_DEEPSEEK_MODEL` settings in `.env.console`.

Settings checks the format of the values. Emulytics tests provider access when generating a journey.

## Choose a provider for a journey

The Wikipedia and Android-version reference goals use built-in rules and templates. They require neither an account nor a language model. For other supported natural-language goals, select a configured provider in the journey editor, enter your goal and generate a draft.

Providers receive text and return draft steps. The console checks those steps against the typed journey contract and the Android driver's allowed actions. Review the draft, publish it and test it on a device.

## Deployment settings

Configuration variables retain the `EMULYTIX_` prefix. The installer creates a private `.env.console`. Keep its encryption key and database credentials with the installation's backup.

For remote console access, terminate HTTPS at a trusted reverse proxy, set `EMULYTIX_PUBLIC_ORIGIN` to the exact public origin and enable secure cookies. The default port remains bound to loopback.

The OpenAI device-code integration targets the local, self-hosted application. For a commercial hosted service, see [Sign in with ChatGPT](https://developers.openai.com/siwc).
