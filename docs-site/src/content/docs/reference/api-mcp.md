---
title: Personal API and MCP
description: Create scoped personal keys and control accepted work through REST or a local MCP client.
---

## Create a personal key

Use **My profile → Personal API & MCP**. Choose a name, permitted profile and expiration. Key creation requires your current password and a fresh TOTP code; a recovery code cannot create a key.

The secret is displayed once. Save it in your secret manager. The server retains its fingerprint, not a retrievable plaintext secret. A lost creation response cannot recover that secret: revoke the possibly created key and create another.

A key's permissions are limited by both its selected scope and the user's current role. Role changes, disabling an account, or password/factor resets revoke keys. Revocation does not erase work already accepted into the queue.

## REST endpoints

Local base URL: `http://localhost:3100/api/v1`. Use HTTPS for a remote installation and `Authorization: Bearer` with a personal key.

| Method and relative path | Permission |
|---|---|
| `GET /capabilities` | Any valid personal key |
| `GET /devices` | `devices.read` |
| `GET /workflows` and `/workflows/{id}/versions/{version}` | `workflows.read` |
| `POST /workflows` | `workflows.publish` |
| `GET /runs`, `/runs/{id}` and `/runs/{id}/events` | `runs.read` |
| `POST /runs` | `runs.execute` |
| `POST /runs/{id}/cancel` | `runs.cancel` |

```bash
curl --fail --silent --show-error   -H "Authorization: Bearer $EMULYTIX_API_KEY"   http://localhost:3100/api/v1/capabilities
```

Lists accept `limit` and `offset`; run events also accept `after`. The API applies a shared per-key limit and returns `429` with a retry interval when exceeded.

For a new launch, choose actual published and device identifiers from your installation:

```json
{
  "workflow_id": "chrome-wikipedia-football",
  "workflow_version": 1,
  "device_ids": ["local-emulator"],
  "max_concurrency": 1,
  "idempotency_key": "my-wikipedia-launch-001",
  "parameters": {}
}
```

After a lost response, keep the same idempotency key and identical body to confirm the accepted launch. Another key means another request. A removed version returns `410` for new work; confirming an already accepted request still returns its original result.

The personal API does not grant user administration, arbitrary ADB commands, provider-token access or managed-emulator system operations. The internal control token and browser cookies are not substitutes for a personal key.

## MCP over stdio

The repository supplies `scripts/emulytix-mcp.py`. A compatible local MCP client launches this process; it uses the same personal REST API and opens no MCP listening port.

```json
{
  "mcpServers": {
    "emulytics": {
      "command": "python3",
      "args": ["/path/to/Emulytics/scripts/emulytix-mcp.py"],
      "env": {
        "EMULYTIX_API_URL": "http://localhost:3100",
        "EMULYTIX_API_KEY": "YOUR_PERSONAL_KEY"
      }
    }
  }
}
```

Keep this client configuration outside the repository and use the client's secret store when available.

Tools are `list_devices`, `list_workflows`, `list_runs`, `get_run`, `get_run_events`, `start_run` and `cancel_run`. Discovery reflects effective permissions; the server still validates every call. Launches require a client-supplied idempotency key and are not automatically retried.

The adapter supports initialization, ping, discovery and tools. It is not an HTTP/OAuth MCP server and exposes no shell or administration tool.
