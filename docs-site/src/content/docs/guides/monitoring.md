---
title: Monitoring and logs
description: Read observed component health, queue metrics and operational evidence.
---

## Dashboard

The dashboard summarizes devices, launches, outstanding work and results. Charts show daily execution outcomes across seven calendar days in the browser timezone, result distribution and current worker capacity.

Launch totals and per-device execution totals are different populations. A launch targeting three devices creates three execution outcomes.

## Component map

**Monitoring** shows the console, APIs, PostgreSQL queue, scheduler, worker and Android paths as a visual component map. Select a block to inspect its measurements and dependencies.

Arrows animate from observed recent activity, not simply because a service exists. Idle, unavailable and unknown states remain distinct. Pause animations or use the reduced-motion preference when needed.

Worker heartbeats expire after twenty seconds. The browser treats a monitoring stream without a new event for ten seconds as stale. A registration or old heartbeat is not proof that Android is connected now.

## Queue and capacity

The queue lives in PostgreSQL. Metrics distinguish queued, leased, active, authentication-waiting and review-required executions, plus oldest queue age and worker occupancy.

Fresh ready workers define processing slots. A device also needs an observed Android connection and an admissible lease state. More registered devices alone do not create execution capacity.

## Results and timings

Result windows are one hour, 24 hours or seven days. Duration and queue-time percentiles include observation counts. A truncated recent-results sample is identified in the interface instead of being presented as the complete window.

Process CPU, memory, database readings and artifact-storage status describe their stated measurement scope; they are not a long-term host monitoring history.

## Log

**Log** combines execution and administrative events with search, categories, levels and pagination. Admin and Auditor can read the audit journal.

The application records reviewed operational metadata rather than passwords, factor seeds, OAuth tokens, API key secrets or complete request bodies. Android screenshots can themselves contain sensitive application data: control access and retention on your installation.
