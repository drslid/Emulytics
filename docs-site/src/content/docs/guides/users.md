---
title: Users and personal security
description: Manage five local roles and the password and authenticator lifecycle.
---

An Admin uses **Users** to create accounts, search and filter the directory, edit identity fields and manage access.

| Role | Main capabilities |
|---|---|
| Admin | All console actions, user administration and account-security actions |
| Builder | Create, publish and delete eligible journey versions; launch, schedule and stop work |
| Operator | Manage devices and run, schedule or stop published journeys |
| Viewer | Read the fleet, published journeys, results, schedules and monitoring |
| Auditor | Viewer access plus audit-journal access |

These are shared-workspace roles. They are not separate customer tenants with isolated fleets and execution histories.

## Identity

Users can maintain first name, last name and contact e-mail in **My profile**. Login usernames remain fixed. Contact e-mail addresses are unique without case sensitivity, but are not verified and are not an e-mail password-recovery channel.

## Administrative actions

- **Reset password:** issue temporary access, close sessions and require password replacement. The existing second factor stays configured.
- **Require password change:** close sessions and request replacement after the current password is entered.
- **Reset 2FA:** close sessions, remove the old factor and recovery codes, then require enrollment again.
- **Close sessions:** revoke browser sessions without changing the user's password or factor.

Changing a role or disabling an account closes its sessions and connections. At least one operational Admin must remain available. An Admin manages their own password and factor from **My profile**, not by resetting themselves through user administration.

## Personal factors

Password and authenticator changes require the current password and a valid confirmation factor. Replacing the authenticator keeps the old factor active until a new code is confirmed. Canceling does not activate the new factor.

Recovery codes are single-use and shown once. Store them privately. The last available code is reserved for recovering the authenticator rather than ordinary sign-in.

Personal API keys are independently revocable. Their scope and lifecycle are described in [Personal API and MCP](/Emulytics/reference/api-mcp/).
