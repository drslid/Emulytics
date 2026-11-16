# Contributing

Emulytics is a self-hosted mobile device control plane. The maintained stack is the React/Next.js console, Python control API and Android worker, Go read API, and PostgreSQL. Public documentation uses Astro/Starlight in `docs-site`.

## Development requirements

- Python 3.12 and Docker Compose for backend tests and disposable PostgreSQL databases.
- Node.js 22.12 or later and npm 10.9.4 for frontend and documentation work.
- Go 1.27.4 or later for the Go API and its security fixes.
- Linux x86-64 with KVM for real emulator testing. Ordinary backend tests do not require Android.

## Run the checks

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r orchestrator-api/requirements.lock
.venv/bin/python -m pip install pytest==9.2.0
.venv/bin/python -m pytest orchestrator-api/tests
```

Frontend:

```bash
cd web-ui
npm ci --ignore-scripts
npm test
npx tsc --noEmit
npm run build
npm audit --audit-level=high
```

Go API:

```bash
cd console-api-go
go test -race -count=1 ./...
go vet ./...
go run golang.org/x/vuln/cmd/govulncheck@v1.9.0 ./...
```

Documentation:

```bash
cd docs-site
npm ci --ignore-scripts
npm run check
npm run build
```

The documentation build validates the static artifact. Preview it with the configured `/Emulytics/` path; repository pages do not run the application or connect to a database.

## Submit a change

Use a focused branch and pull request. Describe the user-visible behavior, include the relevant checks and state any limitations. Preserve authorization, immutable published definitions, device leases, idempotency, cancellation and historical evidence. Database changes require a new migration; do not edit migrations that have already shipped.

Use a small regression test for behavior or security fixes. Verify browser changes in a real browser, including keyboard navigation and a narrow viewport. Keep interface translations consistent across all supported languages.

Do not commit real configuration, credentials, databases, device data, APKs, screenshots of personal data or browser state. Use the private process in [SECURITY.md](SECURITY.md) for security reports. Contributions are licensed under [Apache-2.0](LICENSE); third-party notices remain in [NOTICE](NOTICE).
