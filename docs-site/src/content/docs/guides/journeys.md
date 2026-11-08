---
title: Create and publish journeys
description: Turn an objective into a reviewed draft, publish a version and manage its lifecycle.
---

## Start with natural language

Use **Workflows → Create a workflow** and describe the desired action and observable result. **Prepare my journey** produces a name and a bounded step definition. Review the summary before saving.

Editing the objective invalidates the earlier generation. Generation does not run commands, install an application or publish a version.

The local reference cases are Wikipedia searches and reading the Android version. Other goals use your personal ChatGPT connection and are checked against the existing driver. Unsupported actions are rejected rather than silently omitted.

The generator is not a universal agent for every Android application. It does not invent selectors for an unobserved application, accept arbitrary shell commands, generate social posts or carry out financial operations.

## Drafts and versions

A draft can be edited; a published version freezes the steps, name and instructions used by its executions. Saving a draft does not change older versions or schedules.

The advanced editor can change step arguments and assertions, add, duplicate, reorder or remove steps, or edit bounded JSON. Save, then publish a new version when the change is ready to test.

Concurrent draft changes are detected by revision. A stale save is refused instead of overwriting someone else's work.

## Remove a published version

Admin and Builder have **Delete** under **Published versions**. The confirmation identifies the journey and version number.

Deletion removes that version from future launch and scheduling choices. Its definition, historical results and screenshots remain available. The draft is retained; publishing again creates a higher version number instead of reusing the deleted one.

A version cannot be removed while any schedule references it, including a paused schedule, or while related work is queued or active. The dialog explains the blocker. Remove the referencing schedule or wait for the work to finish, then try again.

A repeated confirmed deletion is safe after a lost response. An old launch dialog receiving a deleted-version response releases its pending request so you can choose another published version.
