#!/usr/bin/env bash
set -euo pipefail

APP_PATH="${APP_PATH:-/home/androidusr/docker-android}"
WEB_UI_PORT="${WEB_UI_PORT:-3000}"
ORCHESTRATOR_API_PORT="${ORCHESTRATOR_API_PORT:-8010}"
AGENT_SERVICE_PORT="${AGENT_SERVICE_PORT:-8011}"

export EMULYTIX_RUNTIME_MODE=local
export AGENT_SERVICE_URL="${AGENT_SERVICE_URL:-http://127.0.0.1:${AGENT_SERVICE_PORT}}"
export EMULYTIX_STORAGE_ROOT="${EMULYTIX_STORAGE_ROOT:-/storage}"
export PUBLIC_ANDROID_STREAM_URL="${PUBLIC_ANDROID_STREAM_URL:-http://localhost:6080/vnc.html?autoconnect=1&resize=scale&show_dot=1}"
export ANDROID_STREAM_PROVIDER="${ANDROID_STREAM_PROVIDER:-novnc}"
export WEB_VNC="${WEB_VNC:-true}"

if mkdir -p "${EMULYTIX_STORAGE_ROOT}" >/dev/null 2>&1 && touch "${EMULYTIX_STORAGE_ROOT}/.writecheck" >/dev/null 2>&1; then
  rm -f "${EMULYTIX_STORAGE_ROOT}/.writecheck"
else
  export EMULYTIX_STORAGE_ROOT="/tmp/emulytix-storage"
  mkdir -p "${EMULYTIX_STORAGE_ROOT}"
fi

mkdir -p /tmp/emulytix-logs

pids=()

shutdown() {
  for pid in "${pids[@]:-}"; do
    if kill -0 "${pid}" >/dev/null 2>&1; then
      kill "${pid}" >/dev/null 2>&1 || true
    fi
  done
  wait || true
}

trap shutdown EXIT INT TERM

if [[ -e /dev/kvm ]]; then
  echo "[emulytix] /dev/kvm detected, starting Android runtime with hardware acceleration"
else
  echo "[emulytix] /dev/kvm not detected, attempting Android runtime in software emulation mode"
  export EMULATOR_ADDITIONAL_ARGS="${EMULATOR_ADDITIONAL_ARGS:-} -accel off -gpu swiftshader_indirect -noaudio -no-boot-anim"
  python3 - <<'PY'
from pathlib import Path

target = Path("/home/androidusr/docker-android/cli/src/device/emulator.py")
text = target.read_text()
old = '        else:\n            raise RuntimeError("/dev/kvm cannot be found!")\n'
new = '        else:\n            self.logger.warning("/dev/kvm cannot be found, continuing with software emulation.")\n            return\n'
if old in text:
    target.write_text(text.replace(old, new))
PY
fi

/bin/bash -lc "${APP_PATH}/mixins/scripts/run.sh" &
pids+=($!)

cd /opt/emulytix/agent-service
/opt/emulytix/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${AGENT_SERVICE_PORT}" &
pids+=($!)

cd /opt/emulytix/orchestrator-api
/opt/emulytix/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${ORCHESTRATOR_API_PORT}" &
pids+=($!)

cd /opt/emulytix/web-ui
npm run start &
pids+=($!)

wait -n
exit $?
