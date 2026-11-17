---
title: Executions and screenshots
description: Follow live Android activity, review step evidence and retry admissible failures.
---

## Launch

Choose a published journey, select the target devices and set parallelism within the selected-device count. The review screen fixes the version, devices and concurrency for the launch. Confirm once.

If the response is lost, use the retained confirmation to check the same request. Changing the request identifier would create another launch.

### Create or adapt a run

From **Executions**, open the run editor and write the journey as numbered [workflow cards](/Emulytics/guides/journeys/). You can ask the configured AI provider to suggest cards from a full description. Edit and prepare the cards, then save a draft or publish the journey and continue to device selection and launch review.

In an existing execution, **Edit and rerun** starts a new draft with the same cards and actions as the published version used for that execution. It proposes the previous target devices when available. Publishing and launching the draft creates a separate execution, preserving the previous result and its screenshots.

## Watch an active execution

Open **Executions** and select the launch. An active device's Android screen appears beside its step screenshots. For a multi-device launch, choose the device to observe.

The live view is read-only, approximately one refreshed image per second. It follows the execution and its current lease. Closing the detail or hiding the browser tab stops demand; a stale image is marked as frozen. Live observation ends when the execution finishes.

## Review the evidence

Each confirmed step stores a screenshot and Android UI hierarchy. The gallery supports step navigation, original-image viewing, capture times and durations. Screenshots remain after the live view ends.

The Android-version objective stores a typed result read from Android system properties. It is displayed independently of the selected screenshot. A skipped, invalid or unconfirmed result is not presented as an observation.

A workflow version's removal from the active catalog does not erase historical evidence.

## Diagnose and retry

For an unsuccessful execution, inspect the failed step, recent events and available screenshots. Controlled retry creates a new linked launch for admissible failed devices using the original version and parameters.

Retry starts the journey again; it does not resume from the exact failed line. It excludes successful devices, active work, quarantine, uncertain effects and journeys with non-repeatable actions. A deleted version cannot receive a new retry.

An accepted retry whose response was lost can still be confirmed using the same request. The interface distinguishes that confirmation from creating new work.
