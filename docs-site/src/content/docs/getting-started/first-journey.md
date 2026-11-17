---
title: Your first journey
description: Run a short natural-language objective and inspect real device evidence.
---

The dashboard's **Your first successful journey** assistant follows device preparation, workflow creation and result verification.

## 1. Select a ready device

Open **Devices** and check that an Android connection is confirmed. The installer prepares a local emulator; other registered devices need their own connection on the correct worker host.

For a managed emulator, use **Power on**, then **Prepare applications** when needed. A name in the fleet does not prove that Android is online.

## 2. Write your cards

In **Workflows → Create a workflow**, write two cards in order.

1. `Open the phone settings.`
2. `Read the Android version.`

You can add a verification to the second card, such as `Record the Android version and API level`. During the test, the workflow reads these values from the selected device. You can also write the complete request in one card.

```text
Open the phone settings and tell me the Android version.
```

For another reference example, use one card.

```text
Open Chrome, go to Wikipedia, search for football and verify the article.
```

These two reference cases use built-in rules and templates. Other supported cards are prepared using the configured [AI provider](/Emulytics/guides/configuration/).

## 3. Review, publish and launch

Choose **Prepare workflow**, review the expected result and the actions, then save the draft. Android runs the steps after you confirm a launch.

Choose **Publish and test**, select one ready device, review the launch and confirm it. A busy device waits in the queue; registration and submission are distinct from execution.

## 4. Inspect the result

Open the execution. The live screen is available while work is active; step screenshots arrive as the worker confirms them. On success, the Android-version journey shows the actual version read from the device above its screenshots.

Check the result instead of assuming every published journey succeeds. A failed assertion or incomplete proof remains an error. [Execution details](/Emulytics/guides/executions/) explain diagnostics and controlled retries.
