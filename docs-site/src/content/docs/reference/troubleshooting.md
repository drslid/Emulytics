---
title: Troubleshooting
description: Resolve common installation, connection, generation and execution blockers.
---

## Docker, KVM or resource check fails

Use `./scripts/install.sh --check` and read the reported prerequisite. Confirm local Docker Engine, the Compose plugin, Linux x86_64, accessible KVM, available RAM and free disk space. Docker Desktop, ARM and remote Docker are outside this installer's supported runtime.

If Linux/WSL reports slightly less than 8 GiB total RAM, increase the guest's memory allocation or explicitly accept reduced capacity with `--allow-low-memory`. Check with `./scripts/install.sh --check --allow-low-memory`, then add the same option to the installation command. At least 4 GiB of available RAM is still required.

Do not delete `.env.console` or add `--volumes` to a shutdown command to fix an unrelated error.

## I cannot find the temporary password

Run `./scripts/account.sh initial-access` in a private terminal. It reports initial access only while it remains valid. Existing enrolled accounts are not reset by re-running installation.

## A worker is unavailable

Check **Monitoring** for a fresh worker heartbeat on the device's exact host. Then check that the correct ADB serial appears as connected. A label on another host or a different serial is not the local emulator.

The Android worker must use the worker Compose profile and its private Android network. Use the supported installer/helper instead of exposing an ADB port.

## The emulator is on but cannot run a journey

**Power on** does not install missing applications. Prepare the selected applications and wait for a confirmed ready state. Missing APKs, a disconnected Android instance, quarantine or active work can block a new launch.

## An objective is unsupported

Start with one of the [reference objectives](/Emulytics/getting-started/first-journey/). Other goals require a personal ChatGPT connection and must fit supported driver capabilities. A connected account does not add arbitrary Android commands, selectors or application workflows.

Describe the complete expected result. The generator refuses extra unsupported actions rather than accepting only part of the instruction.

## A run stays queued

Submission is not execution. Check worker availability, device readiness, the device lease and the launch concurrency limit. One worker process executes one journey at a time.

## A screenshot or result is missing

Open the failed step and diagnostic. An assertion, screenshot or UI-hierarchy collection failure prevents that step from publishing successful evidence. The system does not replace a failed read with a guessed result.

The current runtime can emit continuous accessibility events on some Settings pages. The Android-version reference journey opens main Settings and reads fixed Android properties; it does not depend on OCR of the About page.

## A published version cannot be deleted

Remove every referencing schedule, even paused schedules, and wait for queued or active executions to finish. System versions for emulator management cannot be deleted from the journey catalog.

A deleted version remains visible through its historical execution. Its absence from new launch choices is intentional.

## A request timed out

For a retained launch or retry confirmation, check the same request. Do not generate another request identity merely because a response was lost. A definitive deleted-version refusal releases the form for another selection.

## Contact e-mail did not receive a reset message

Contact e-mail is not verified and no recovery e-mail is sent. Use an available factor, a recovery code or the local administrator's account-management procedure.
