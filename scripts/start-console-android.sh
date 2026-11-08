#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077

bench_container="${EMULYTIX_BENCH_CONTAINER:-emulytix-wf01-android}"
bench_network="${EMULYTIX_BENCH_NETWORK:-emulytix-wf01-bench}"
boot_timeout="${EMULYTIX_BENCH_BOOT_TIMEOUT:-180}"
[[ "$boot_timeout" =~ ^[1-9][0-9]{0,2}$ ]] || { echo "Délai de démarrage Android invalide." >&2; exit 1; }
[[ "$bench_container" == emulytix-wf01-* && "$bench_network" == emulytix-wf01-* ]] || {
  echo "Les noms du banc doivent commencer par emulytix-wf01-." >&2
  exit 1
}
[[ -f .env.console ]] || { echo "Démarrez d'abord scripts/start-console.sh." >&2; exit 1; }
console=(docker compose --env-file .env.console -p emulytix-preview -f docker-compose.preview.yml)
for service in console-postgres console-api; do
  [[ -n "$("${console[@]}" ps --status running -q "$service")" ]] || {
    echo "$service doit être démarré avec scripts/start-console.sh." >&2
    exit 1
  }
done

if docker container inspect "$bench_container" >/dev/null 2>&1; then
  label="$(docker inspect --format '{{ index .Config.Labels "emulytix.bench" }}' "$bench_container")"
  running="$(docker inspect --format '{{.State.Running}}' "$bench_container")"
  [[ "$label" == wf01 ]] || {
    echo "Le conteneur existant n'est pas un banc Emulytix ; aucun remplacement effectué." >&2
    exit 1
  }
  if [[ "$running" != true ]]; then
    [[ "$running" == false ]] || { echo "L’état du banc est inconnu. Aucun redémarrage effectué." >&2; exit 1; }
    persistence="$(docker inspect --format '{{ index .Config.Labels "emulytix.bench.persistence" }}' "$bench_container")"
    command="$(docker inspect --format '{{json .Config.Cmd}}' "$bench_container")"
    entrypoint="$(docker inspect --format '{{json .Config.Entrypoint}}' "$bench_container")"
    if [[ "$persistence" != preserve-avd-v1 ]] || ! printf '%s' "$command" | python3 -c '
import json, sys
try:
    assert json.loads(sys.argv[1]) == ["/bin/bash"]
    command = json.load(sys.stdin)
    assert isinstance(command, list) and len(command) == 2 and command[0] == "-lc"
    source = command[1]
    assert isinstance(source, str)
    assert '\''if [[ ! -f "$ANDROID_AVD_HOME/emulytix-wf01.ini" ]]; then'\'' in source
    assert "avdmanager create avd --name emulytix-wf01" in source
    assert "--force" not in source and "-wipe-data" not in source
except (ValueError, AssertionError, TypeError):
    raise SystemExit(1)
' "$entrypoint"; then
      echo "Ce banc arrêté utilise une ancienne commande ou une configuration inconnue susceptible de recréer Android. Aucun redémarrage ni remplacement effectué. Conservez le conteneur et sauvegardez ses données avant de préparer sa migration." >&2
      exit 1
    fi
  fi
else
  android-runtime/scripts/start-bench.sh
fi

# Verify the declared private network and Android before registering or starting a worker.
network_label="$(docker network inspect --format '{{ index .Labels "emulytix.bench" }}' "$bench_network")"
[[ "$network_label" == wf01 ]] || { echo "Réseau privé du banc non reconnu." >&2; exit 1; }
networks="$(docker inspect --format '{{range $name, $network := .NetworkSettings.Networks}}{{$name}}{{"\n"}}{{end}}' "$bench_container")"
[[ $'\n'"$networks"$'\n' == *$'\n'"$bench_network"$'\n'* ]] || {
  echo "Le banc n'est pas connecté au réseau attendu." >&2
  exit 1
}
if [[ "${running:-true}" != true ]]; then docker start "$bench_container" >/dev/null; fi
deadline=$((SECONDS + boot_timeout))
while (( SECONDS < deadline )); do
  booted="$(docker exec "$bench_container" timeout 5 adb -H 127.0.0.1 -P 5037 -s emulator-5554 shell getprop sys.boot_completed 2>/dev/null | tr -d '\r\n' || true)"
  [[ "$booted" == 1 ]] && break
  [[ "$(docker inspect --format '{{.State.Running}}' "$bench_container")" == true ]] || break
  sleep 2
done
[[ "${booted:-}" == 1 ]] || { echo "Android n'a pas terminé son démarrage. Les données sont conservées ; relancez après diagnostic." >&2; exit 1; }

"${console[@]}" exec -T console-api python - <<'PY'
import os
import urllib.request

from app.run_models import DeviceRegistration
from app.run_store import RunStore

with urllib.request.urlopen('http://127.0.0.1:8010/health', timeout=3) as health:
    if health.status != 200:
        raise SystemExit('API indisponible')
store = RunStore(os.environ['EMULYTIX_DATABASE_URL'])
with store.connect() as connection:
    existing = connection.execute(
        'SELECT device_id FROM devices WHERE host_id=%s AND serial=%s',
        ('bench-host', 'emulator-5554'),
    ).fetchone()
if existing:
    device_id = existing['device_id']
else:
    record, _ = store.register_device(DeviceRegistration(
        device_id='local-emulator', display_name='Émulateur local',
        host_id='bench-host', serial='emulator-5554', kind='emulator',
    ))
    device_id = record['device_id']
print('Appareil disponible dans la console : ' + device_id)
PY

mkdir -p storage/runtime-apks
# Keep this bench bound to its own host; never retarget existing user devices.
export EMULYTIX_HOST_ID=bench-host
export ADB_SERVER_SOCKET="tcp:${bench_container}:5037"
export EMULYTIX_BENCH_NETWORK="$bench_network"
worker=("${console[@]}" -f docker-compose.console-worker.yml --profile worker)
"${worker[@]}" up -d --build console-worker
"${worker[@]}" exec -T console-worker python - <<'PY'
import subprocess

result = subprocess.run(
    ['adb', '-s', 'emulator-5554', 'shell', 'getprop', 'sys.boot_completed'],
    check=True, capture_output=True, text=True, timeout=10,
)
if result.stdout.strip() != '1':
    raise SystemExit('Le worker ne peut pas joindre Android.')
PY
printf '%s\n' 'Android local prêt : http://localhost:3100/telephones' \
  'Choisissez Émulateur local (ou le nom existant), puis le parcours Recherche Wikipédia.' \
  'Aucun nouveau parcours n’a été lancé. Le worker peut reprendre les demandes déjà en attente sur bench-host.'
