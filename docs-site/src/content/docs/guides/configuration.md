---
title: Settings and AI providers
description: Configure OpenAI, local Ollama or DeepSeek to draft supported journeys.
---

Open **Settings** to see the available AI providers and connection status. Passwords and second factors are managed under **My profile**.

![Settings showing OpenAI and the configured models for Ollama and DeepSeek](/Emulytics/brand/console/settings.png)

Settings in a demonstration workspace.

## Connect OpenAI

1. Choose the connection action under **OpenAI** in **Settings**.
2. Open the official URL supplied by the device-code flow.
3. Sign in with your ChatGPT account and enter the displayed device code.
4. Return to the console and wait for confirmation.

Wait for confirmation in the console. A pending code expires or can be canceled. You can disconnect your account from the installation later.

Each OpenAI connection belongs to one local user. The server uses an isolated official Codex process and encrypted storage.

## Configure Ollama or DeepSeek

An installation administrator configures these providers in the private `.env.console` file. The configuration is shared across the installation and is used from the control API.

For **Ollama**, start your local Ollama server and download the model with `ollama pull <model>`. To keep inference local, enable `OLLAMA_NO_CLOUD=1` in the Ollama server environment. Use the URL reachable by the control API and the exact model tag installed in Ollama.

```dotenv
EMULYTIX_OLLAMA_URL=http://host.docker.internal:11434
EMULYTIX_OLLAMA_MODEL=your-local-model-tag
```

With Docker, `host.docker.internal` resolves to the host gateway. If Ollama listens only on `127.0.0.1`, set `OLLAMA_HOST` to an address reachable from the Docker network and restart Ollama. For a control API running directly on the same host, use `http://127.0.0.1:11434`.

For **DeepSeek**, add a DeepSeek API key and choose a supported model. DeepSeek receives the text of the generation request over HTTPS. Keep the key on the server.

```dotenv
EMULYTIX_DEEPSEEK_API_KEY=your-deepseek-api-key
EMULYTIX_DEEPSEEK_MODEL=deepseek-flash
```

Restart the console services with `./scripts/start-console.sh` after updating `.env.console`, then check the provider in **Settings**. See the [Ollama documentation](https://docs.ollama.com/) and [DeepSeek API documentation](https://api-docs.deepseek.com/) for available models.

## Choose a provider for a journey

The Wikipedia and Android-version reference goals use built-in rules and templates. They require neither an account nor a language model. For other supported natural-language goals, select a configured provider in the journey editor, enter your goal and generate a draft.

Providers receive text and return draft steps. The console checks those steps against the typed journey contract and the Android driver's allowed actions. Review the draft, publish it and test it on a device.

## Deployment settings

Configuration variables retain the `EMULYTIX_` prefix. The installer creates a private `.env.console`. Keep its encryption key and database credentials with the installation's backup.

For remote console access, terminate HTTPS at a trusted reverse proxy, set `EMULYTIX_PUBLIC_ORIGIN` to the exact public origin and enable secure cookies. The default port remains bound to loopback.

The OpenAI device-code integration targets the local, self-hosted application. For a commercial hosted service, see [Sign in with ChatGPT](https://developers.openai.com/siwc).
