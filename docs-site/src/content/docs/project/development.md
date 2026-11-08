---
title: Development and contributions
description: Find the active components and run their focused checks locally.
---

## Repository structure

| Directory | Purpose |
|---|---|
| `web-ui/` | Next.js/React console, styles and same-origin proxies |
| `orchestrator-api/` | Python control API, sessions, PostgreSQL stores, scheduler and Android worker |
| `console-api-go/` | Migrated summary, fleet and dashboard reads |
| `android-runtime/` | Reproducible emulator image and runtime scripts |
| `workflows/` | Bundled deterministic journey versions |
| `scripts/` | Installer, local account tooling and stdio MCP adapter |
| `docs-site/` | Public Astro/Starlight documentation |

## Application checks

Use the committed locks for dependency installation. The Python development environment needs the locked application dependencies and test dependencies. API tests create isolated PostgreSQL containers, so a running local Docker daemon is required.

```bash
python3 -m pytest orchestrator-api/tests -q
npm --prefix web-ui test
(cd web-ui && npx tsc --noEmit)
npm --prefix web-ui run build
```

Run Go checks from `console-api-go/`:

```bash
go test -race ./...
go vet ./...
```

See the repository's [contribution guide](https://github.com/drslid/Emulytics/blob/main/CONTRIBUTING.md) for development setup and review expectations.

## Documentation checks

From `docs-site/`, with Node 22.12 or newer:

```bash
npm ci --ignore-scripts
npm run check
npm run build
npm run dev -- --host 127.0.0.1
```

The site is static and follows the `/Emulytics/` GitHub Pages base path. Search is built locally with Pagefind. The build validates links and assets and checks that operational files are absent from its artifact.

Only authored public pages and explicit brand assets belong in this site. Do not import local storage, user screenshots, authenticator images, credential files or populated operational reports.

## Reporting problems

For an ordinary bug, include the affected version, steps, expected result and redacted diagnostics. For a vulnerability, use the [security policy](https://github.com/drslid/Emulytics/blob/main/SECURITY.md) rather than publishing credentials or private evidence in an issue.
