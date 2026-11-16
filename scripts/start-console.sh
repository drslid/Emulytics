#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077

EMULYTIX_VERSION="$(<VERSION)"
[[ "$EMULYTIX_VERSION" =~ ^(0|[1-9][0-9]{0,5})(\.(0|[1-9][0-9]{0,5})){2}$ ]] || { echo "Version Emulytics invalide." >&2; exit 1; }
export EMULYTIX_VERSION
mkdir -p storage/updates/{requests,status}

python3 - <<'PY'
import base64
import os
from pathlib import Path
import secrets

environment = Path('.env.console')
if not environment.exists():
    password = secrets.token_hex(24)
    lines = {
        'EMULYTIX_POSTGRES_PASSWORD': password,
        'EMULYTIX_DATABASE_URL': f'postgresql://emulytix_console:{password}@console-postgres:5432/emulytix',
        'EMULYTIX_CONTROL_TOKEN': secrets.token_urlsafe(32),
        'EMULYTIX_AUTH_KEY': base64.urlsafe_b64encode(os.urandom(32)).decode(),
        'EMULYTIX_PUBLIC_ORIGIN': 'http://localhost:3100',
        'EMULYTIX_COOKIE_SECURE': 'false',
    }
    with environment.open('x') as output:
        output.write('\n'.join(f'{key}={value}' for key, value in lines.items())+'\n')
    environment.chmod(0o600)
Path('storage/runs').mkdir(parents=True, exist_ok=True)
PY

console=(docker compose --env-file .env.console -p emulytix-preview -f docker-compose.preview.yml)
if [[ "${EMULYTIX_UPDATING:-}" == 1 ]]; then
  dependencies=(--no-deps)
  migration_build=()
  service_build=(--no-build)
else
  dependencies=()
  migration_build=(--build)
  service_build=(--build)
  "${console[@]}" up -d console-postgres
fi
"${console[@]}" run "${dependencies[@]}" "${migration_build[@]}" --rm console-migrate
"${console[@]}" up "${dependencies[@]}" -d "${service_build[@]}" console-api console-go-api console-scheduler validation-ui
python3 scripts/bootstrap-console.py
"${console[@]}" exec -T console-api python -c '
import json, os
from pathlib import Path
from fastapi import HTTPException
from app.run_models import WorkflowRegistration
from app.run_store import RunStore
workflow = WorkflowRegistration.model_validate_json(Path("/workflows/chrome-wikipedia-football.v1.json").read_text())
try:
    RunStore(os.environ["EMULYTIX_DATABASE_URL"]).register_workflow(workflow)
except HTTPException as error:
    if error.status_code != 410 or error.detail != {"code": "workflow_version_deleted"}:
        raise
    print("WF01 reste supprimé du catalogue, conformément à votre choix.")
else:
    print("WF01 disponible dans le catalogue.")
'
printf '%s\n' 'Console : http://localhost:3100' 'Accès initial : scripts/account.sh initial-access'
