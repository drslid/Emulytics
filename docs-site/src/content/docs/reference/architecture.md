---
title: Architecture
description: Understand the console, APIs, PostgreSQL queue and Android worker boundaries.
---

![Conceptual component flow from the browser through the console and APIs to PostgreSQL, workers and Android.](/Emulytics/brand/architecture.svg)

The illustration is an architectural guide, not a live monitoring view.

## Components

| Component | Responsibility |
|---|---|
| Next.js / React console | User interface, authentication screens and same-origin API proxies |
| Python API | Session and role authority, journey mutations, schedules, personal keys and device registration |
| Go API | Selected reads: summary, fleet and dashboard aggregates |
| PostgreSQL | Accounts, immutable versions, schedules, queue, idempotency records, leases and audit metadata |
| Scheduler | Submit due occurrences with stable request identities |
| Android worker | Claim work, hold a device lease, execute bounded actions and save evidence |
| Android runtime | Persistent emulator containers and their private ADB connection |

The migration to Go is progressive. It does not replace every Python route or the current authentication authority.

## Work and lease model

PostgreSQL persists execution work. Workers claim admissible items with locking, enforce per-launch concurrency and reserve the selected device. Lease epochs and validity checks prevent an expired owner from continuing to issue authorized commands.

Every effectful Android command passes the command guard and action journal. Screenshots and observations are associated with the execution and step. Cancellation is a request until the worker confirms its result.

## Private services

The normal Compose deployment publishes the web console on `127.0.0.1:3100`. Database and Android control ports are not public. Only the worker receives the Docker socket for managed-emulator operations; that worker is a highly trusted host component.

The browser uses session cookies through the same-origin BFF. The personal `/api/v1` interface uses scoped Bearer keys. Internal control credentials are not browser credentials or personal API keys.

## Storage and lifecycle

PostgreSQL uses a named volume. Emulator data volumes survive normal stop/start. Execution artifacts live under local storage and are served only through authenticated, ownership-checked capture routes.

A retired published version remains in storage for historical execution evidence. It is absent from active catalog reads and cannot receive new work. New publication numbers keep increasing.

The GitHub Pages documentation is a separate static artifact. It does not connect to an installation, run Android, or serve its databases and captures.
