---
title: Schedules
description: Schedule a published version using simple calendar choices or five-field CRON.
---

Open **Schedules → Create** or choose **Schedule** beside a published version. Set a name, devices, concurrency and timezone.

The simple mode covers daily, weekly and monthly runs. Advanced mode accepts a five-field CRON expression:

```text
minute hour day-of-month month day-of-week
```

For example, `0 9 * * 1-5` means weekdays at 09:00 in the schedule's selected timezone. The interface previews the next five UTC instants using that timezone; browser timezone detection does not silently change a saved schedule.

## Time and missed occurrences

Schedules use an explicit IANA timezone such as `Europe/Paris`. A local time that does not exist at the spring clock change is skipped. A repeated local time at the autumn change runs only on its first occurrence.

Pause preserves the schedule. Resume starts at the next future occurrence. After a service interruption, one overdue occurrence is submitted, then the cursor moves forward; the scheduler does not replay every missed slot in a burst.

The scheduler checks due work approximately every five seconds. Submission still requires a worker and a ready Android device before execution can start.

## Permissions and version lifecycle

The schedule owner must remain active, fully enrolled and allowed to execute journeys. Losing that permission disables the schedule.

A schedule always refers to one published version. Editing a draft does not move existing schedules to a newer publication. Delete and recreate a schedule when its full configuration or version needs to change.

A referenced version remains protected from deletion even while its schedule is paused. Remove the schedule first. If a version was deleted from another browser tab before a new schedule was accepted, choose another available version in the form.
