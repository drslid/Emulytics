# Device management and run creation

**Goal** — Edit and remove devices in Emulytics, expose managed emulator power controls, and use the reference execution editor to improve run creation.

## Devices

- [x] Add `PATCH /console/devices/{device_id}` for the display name. Keep the device identity and existing execution references stable. Verify the editor and action availability for operator, administrator and read-only roles.
- [x] Add `DELETE /console/devices/{device_id}` for inventory removal. Preserve historical runs and the data of stopped emulators. Block removal when a device is busy or selected by an enabled schedule. Verify that removed devices leave inventory and new work cannot target them, including after an application rollback.
- [x] Surface inventory removal, naming and managed emulator power controls from Devices. Explain the effect of removal in the confirmation. Reuse the existing queued start and stop operations for managed emulators.

## Runs and reference review

- [x] Inspect the reference editor and reachable navigation in SmartIQ using read-only views. Record the actual fields, layout, actions and limits observed.
- [x] Add `/activite/nouveau` for Android run authoring. Seed a separate draft from the exact published version of a source execution when requested. Reuse launch review and preserve execution history. Verify draft replay and the previous version's ability to use active devices.
