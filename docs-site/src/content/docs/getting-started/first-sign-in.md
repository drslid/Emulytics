---
title: First sign-in
description: Replace the generated password and enable mandatory two-factor authentication.
---

The first local account is `admin`. Its generated temporary password is available only through the installation's private account tool:

```bash
./scripts/account.sh initial-access
```

1. Open **http://localhost:3100** on the installation host.
2. Enter `admin` and the temporary password.
3. Choose a personal password when prompted.
4. Scan the enrollment QR code with an authenticator such as Google Authenticator or 2FAS.
5. Enter the application's current six-digit code.
6. Save the recovery codes in a password manager before opening the console.

Two-factor authentication is mandatory. The console does not expose operational pages until password replacement and TOTP enrollment are complete. Recovery codes are shown once.

## After enrollment

Use **My profile → Account security** to change your password, replace your authenticator or renew recovery codes. Sensitive actions require the current password and an available confirmation factor. Changing a password or authenticator closes other sessions and rotates the current session.

The contact e-mail address is not a password-reset service: the application does not send verification or recovery messages.

## Create other users

An Admin can use **Users** to create local accounts, assign roles and generate temporary access. Each new user replaces their password and enrolls their own authenticator.

Keep at least one active, fully enrolled Admin. The server protects the last operational administrator from actions that would leave the installation without one.

Continue with [Your first journey](/Emulytics/getting-started/first-journey/).
