---
title: Your first journey
description: Run a short natural-language objective and inspect real device evidence.
---

The dashboard's **Your first successful journey** assistant follows device preparation, objective creation and result verification.

## 1. Select a ready device

Open **Devices** and check that an Android connection is confirmed. The installer prepares a local emulator; other registered devices need their own connection on the correct worker host.

For a managed emulator, use **Power on**, then **Prepare applications** when needed. A name in the fleet does not prove that Android is online.

## 2. Describe the objective

In **Workflows → Create a workflow**, write:

```text
Open the phone settings and tell me the Android version.
```

The reference goal prepares two bounded steps: open Settings and read Android's release and API level from the selected device. No version is guessed during generation.

Another reference objective is:

```text
Open Chrome, go to Wikipedia, search for football and verify the article.
```

These two reference cases work without a ChatGPT account. Other objectives require the personal connection described in [Configuration](/Emulytics/guides/configuration/) and must remain within supported capabilities.

## 3. Review, publish and launch

Choose **Prepare my journey**, review the name, expected result and steps, then save the draft. Generation does not control Android or publish a version.

Choose **Publish and test**, select one ready device, review the launch and confirm it. A busy device waits in the queue; registration and submission are distinct from execution.

## 4. Inspect the result

Open the execution. The live screen is available while work is active; step screenshots arrive as the worker confirms them. On success, the Android-version journey shows the actual version read from the device above its screenshots.

Check the result instead of assuming every published journey succeeds. A failed assertion or incomplete proof remains an error. [Execution details](/Emulytics/guides/executions/) explain diagnostics and controlled retries.
