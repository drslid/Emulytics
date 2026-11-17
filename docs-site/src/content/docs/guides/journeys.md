---
title: Create and publish journeys
description: Write editable Android workflow cards, review their actions and publish a version.
---

## Write the steps as cards

Open **Workflows → Create a workflow**. Write one instruction per card, such as `Open LinkedIn`. Emulytics finds the app from its name. Add, reorder or remove cards as needed. Use **Add verification** to say what Android should check after an instruction.

![Workflow editor showing two plain-language steps, an optional verification and the prepared actions](/Emulytics/brand/console/workflow-cards.png)

To start from a single description, open **Help me create steps**, describe the whole task and choose **Create cards**. Edit the resulting cards before preparing the workflow. [AI provider setup](/Emulytics/guides/configuration/)

## Prepare and review

Choose **Prepare** to review the Android actions for the current cards. When a card needs more detail, the message appears next to it. Edit the card and prepare again. Save the draft, then publish and confirm a test to run the reviewed actions.

The Wikipedia search and Android-version examples use built-in rules. Other supported instructions use the configured provider. The console checks the actions the driver can execute, such as opening an app or web page, reading Android version information and taking a screenshot. When the editor already has a target device, supported preparation can use known apps on that device.

## Drafts and versions

A draft remains editable. Each published version keeps its own ordered cards, Android actions and name. Runs and schedules continue to use the published version they selected.

When you open a workflow created before cards were introduced, write the instructions as cards and prepare them before saving. Past executions keep their original version and evidence.

Concurrent draft changes are detected by revision. A stale save is refused instead of overwriting someone else's work.

## Remove a published version

Admin and Builder have **Delete** under **Published versions**. The confirmation identifies the journey and version number.

Deletion removes that version from future launch and scheduling choices. Its definition, historical results and screenshots remain available. The draft is retained; publishing again creates a higher version number instead of reusing the deleted one.

A version cannot be removed while any schedule references it, including a paused schedule, or while related work is queued or active. The dialog explains the blocker. Remove the referencing schedule or wait for the work to finish, then try again.

A repeated confirmed deletion is safe after a lost response. An old launch dialog receiving a deleted-version response releases its pending request so you can choose another published version.
