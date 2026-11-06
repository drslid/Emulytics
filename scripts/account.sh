#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec docker compose --env-file .env.console -p emulytix-preview -f docker-compose.preview.yml exec console-api python -m app.auth_admin "$@"
