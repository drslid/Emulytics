---
title: Install
description: Install the console and a local Android runtime on a supported Linux host.
---

## Requirements

| Requirement | Supported configuration |
|---|---|
| Host | Linux x86_64 with hardware virtualization and `/dev/kvm` |
| Container engine | Local Docker Engine and Docker Compose plugin |
| Tools | Git, Bash and Python 3 |
| Memory | At least 8 GiB total, with 4 GiB available at startup |
| Free storage | At least 25 GiB for images, dependencies and Android data |
| Network | Access to package registries, container registries and official Android archives |

Docker and Compose must already be installed. The installer checks them; it does not install Docker or configure your host's virtualization.

## Install from the repository

```bash
git clone https://github.com/drslid/Emulytics.git
cd Emulytics
./scripts/install.sh --accept-android-license
```

`--accept-android-license` confirms acceptance of the [Android SDK terms](https://developer.android.com/studio/terms). Review those terms before running the command. The first build downloads roughly 1.8 GB of Android archives, plus application and container dependencies.

The command verifies prerequisites, creates private configuration only when it is missing, builds the Android image from verified archives, applies database migrations and starts the console, scheduler and worker. It preserves existing configuration, accounts and Android volumes on a retry.

Open **http://localhost:3100**. Use that exact origin; `127.0.0.1` is a different browser origin.

## Check prerequisites only

```bash
./scripts/install.sh --check
```

This check does not create configuration or start the stack.

The memory diagnostic reports what Linux can actually use. A VM or WSL guest configured with 8 GiB may expose slightly less to Linux and fail the strict 8 GiB total-memory check. Prefer increasing the memory allocated to the guest. To explicitly accept reduced capacity on a smaller host, run:

```bash
./scripts/install.sh --check --allow-low-memory
./scripts/install.sh --accept-android-license --allow-low-memory
```

This option only relaxes the total-memory requirement. At least 4 GiB must still be available at startup; the Docker, KVM and storage checks remain required. Running several emulators may require more memory.

## First access

In a private terminal, retrieve the temporary access:

```bash
./scripts/account.sh initial-access
```

Continue with [First sign-in](/Emulytics/getting-started/first-sign-in/). Ordinary installation logs do not print the password.

## Existing installations

Re-running the same installer verifies or resumes the installation. It does not reset existing users. A worker may resume already queued work when it becomes available.

Keep `.env.console`: it contains the database credentials and encryption key required to read encrypted account factors and ChatGPT connections. Do not regenerate it to fix an unrelated problem.

The full emulator installer does not support ARM, Docker Desktop on macOS or Windows, or a remote Docker daemon. See [status and scope](/Emulytics/project/status/) before choosing a host.
