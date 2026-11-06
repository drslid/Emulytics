#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077

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
"${console[@]}" up -d console-postgres
"${console[@]}" run --build --rm console-migrate
"${console[@]}" up -d --build console-api console-scheduler validation-ui
python3 scripts/bootstrap-console.py
"${console[@]}" exec -T console-api python -c '
import json, os
from pathlib import Path
from app.run_models import WorkflowRegistration
from app.run_store import RunStore
workflow = WorkflowRegistration.model_validate_json(Path("/workflows/chrome-wikipedia-football.v1.json").read_text())
RunStore(os.environ["EMULYTIX_DATABASE_URL"]).register_workflow(workflow)
print("WF01 disponible dans le catalogue.")
'
printf '%s\n' 'Console : http://localhost:3100' 'Accès initial : scripts/account.sh initial-access'
