---
title: Devices and emulators
description: Register Android devices, prepare emulator applications and operate selected groups.
---

## Create a managed emulator

Open **Devices → Create an emulator**, enter a human-readable name, choose a worker host and select applications. Names can contain spaces; technical identifiers are generated for you.

Chrome comes from the runtime image. The initial Snapchat, LinkedIn, Instagram and TikTok entries require compatible standalone APK files that you provide and are authorized to use. Uploading an APK identifies its package, and an unavailable file stays visibly unavailable. Play Store installation and split APK bundles are outside the current scope.

### Find an APK on F-Droid

1. In **Desired applications**, search F-Droid by application name or package ID.
2. Select an application and then a release. The picker shows the version, version code and date added to F-Droid, in UTC.
3. Import the release and complete the emulator configuration. The imported application is selected for this emulator.
4. Run **Prepare applications** to install the selected APKs and check that they are ready.

![Emulator creation form with the F-Droid search, K-9 Mail and the selected version and date](/Emulytics/brand/console/apk-search.png)

F-Droid search in a demonstration workspace.

Search results show standalone releases compatible with the managed Android 10 runtime. Android rejects a downgrade when a release with a higher version code is already installed. You can also upload a compatible standalone APK from another source. An emulator can have up to 12 selected applications.

The controls have separate effects:

| Control | Effect |
|---|---|
| Power on | Start Android without installing missing applications |
| Prepare applications | Start if needed, install the selected verified APKs and check installation |
| Power off | Stop the emulator while preserving its data volume |
| Launch a journey | Use an emulator whose applications and Android connection are ready |

Deselecting an application does not uninstall it.

## Screen and resources

Presets and advanced settings cover width, height, density, RAM, CPU cores and initial storage. The recommended profile is 720 × 1280 at 320 dpi, 1536 MiB RAM, two CPU cores and 8 GiB initial storage.

Screen, RAM and CPU changes require a stopped emulator without queued work or an active or uncertain lease. The next start reuses the owned data volume and verifies the applied display profile. Storage can be chosen before initialization; resizing an existing Android data image is not supported.

Configured storage and measured Android capacity are different values. A value shown as unmeasured is not replaced with an invented capacity.

## Register an existing device

Use the existing-device flow for a physical Android device or an external emulator. Choose the worker host and exact ADB serial. Registering a label does not connect a phone, authorize USB debugging or start an emulator.

Admin and Operator can manage devices. Builder can launch published journeys on a device that is already ready.

## Groups and capacity

Create a named group, select its devices, then use the available group actions. Bulk power and application preparation apply only to managed emulators explicitly selected in the interface. Physical devices do not gain virtual power controls from group membership.

Capacity is based on fresh worker heartbeats and available devices. One worker process executes one journey at a time, and one device has at most one active execution. Additional workers and devices can increase concurrency within the host's actual CPU, memory and storage limits. The 100-device request limit is a contract limit, not a load-test result.
