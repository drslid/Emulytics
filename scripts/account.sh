#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${1:-}" == "initial-access" && "$#" -eq 1 ]]; then
  exec python3 scripts/bootstrap-console.py --show
fi
exec docker compose --env-file .env.console -p emulytix-preview -f docker-compose.preview.yml exec console-api python -m app.auth_admin "$@"
