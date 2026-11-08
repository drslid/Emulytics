#!/usr/bin/env bash
set -euo pipefail

# Reproducible Android 10 / Chrome baseline; Android 14 is a separate runtime target.
bench_image="${EMULYTIX_BENCH_IMAGE:-emulytix/android-runtime:0.9.0}"
bench_container="${EMULYTIX_BENCH_CONTAINER:-emulytix-wf01-android}"
bench_network="${EMULYTIX_BENCH_NETWORK:-emulytix-wf01-bench}"
boot_timeout="${EMULYTIX_BENCH_BOOT_TIMEOUT:-180}"

[[ "$bench_container" == emulytix-wf01-* && "$bench_network" == emulytix-wf01-* ]] || {
  echo "Bench container and network names must start with emulytix-wf01-." >&2
  exit 1
}
[[ "$boot_timeout" =~ ^[1-9][0-9]{0,2}$ ]] || { echo "Invalid boot timeout." >&2; exit 1; }
[[ -c /dev/kvm ]] || { echo "This bench requires /dev/kvm." >&2; exit 1; }
docker image inspect "$bench_image" >/dev/null
if docker container inspect "$bench_container" >/dev/null 2>&1; then
  echo "Container $bench_container already exists; this command never replaces it." >&2
  exit 1
fi

docker run --rm --name "${bench_container}-preflight-$$" --device /dev/kvm \
  --entrypoint /bin/bash "$bench_image" -lc '
    set -e
    test -x /opt/android-sdk/emulator/emulator
    test -x /opt/android-sdk/platform-tools/adb
    command -v avdmanager >/dev/null
    test -d /opt/android-sdk/system-images/android-29/google_apis/x86_64
    /opt/android-sdk/emulator/emulator -accel-check
  '

created_container=false
created_network=false
ready=false
container_id=""
cleanup_failed_start() {
  if [[ "$ready" == false ]]; then
    if [[ "$created_container" == true ]]; then
      docker logs "$bench_container" >&2 || true
      docker cp "$container_id:/tmp/adb-server.log" - | tar -xO >&2 || true
      docker cp "$container_id:/tmp/emulator.log" - | tar -xO >&2 || true
      docker rm --force --volumes "$container_id" >/dev/null || true
    fi
    if [[ "$created_network" == true ]]; then docker network rm "$bench_network" >/dev/null || true; fi
  fi
}
trap cleanup_failed_start EXIT
if ! docker network inspect "$bench_network" >/dev/null 2>&1; then
  docker network create --label emulytix.bench=wf01 "$bench_network" >/dev/null
  created_network=true
fi

container_id="$(docker create --name "$bench_container" --network "$bench_network" --restart unless-stopped \
  --label emulytix.bench=wf01 --label emulytix.bench.persistence=preserve-avd-v1 \
  --device /dev/kvm --memory 3g --cpus 2 --shm-size 256m \
  --env ANDROID_AVD_HOME=/project/.android-user/avd --entrypoint /bin/bash "$bench_image" -lc '
    set -e
    mkdir -p "$ANDROID_AVD_HOME"
    if [[ ! -f "$ANDROID_AVD_HOME/emulytix-wf01.ini" ]]; then
      echo no | avdmanager create avd --name emulytix-wf01 \
        --package "system-images;android-29;google_apis;x86_64"
    fi
    adb -a -P 5037 nodaemon server > /tmp/adb-server.log 2>&1 &
    adb_pid=$!
    for attempt in $(seq 1 50); do
      if (: > /dev/tcp/127.0.0.1/5037) 2>/dev/null; then break; fi
      kill -0 "$adb_pid" || { cat /tmp/adb-server.log >&2; exit 1; }
      sleep 0.1
    done
    (: > /dev/tcp/127.0.0.1/5037) 2>/dev/null || { cat /tmp/adb-server.log >&2; exit 1; }
    /opt/android-sdk/emulator/emulator -avd emulytix-wf01 -no-window -no-audio \
      -no-boot-anim -no-snapshot -gpu swiftshader_indirect -memory 1536 -cores 2 \
      -port 5554 -accel on > /tmp/emulator.log 2>&1 &
    wait -n
  ')"
created_container=true
docker start "$container_id" >/dev/null

deadline=$((SECONDS + boot_timeout))
while (( SECONDS < deadline )); do
  # Explicit remote host prevents this probe from auto-starting a loopback-only ADB server.
  booted="$(docker exec "$bench_container" timeout 5 adb -H 127.0.0.1 -P 5037 -s emulator-5554 \
    shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)"
  if [[ "$booted" == 1 ]]; then ready=true; break; fi
  if [[ "$(docker inspect --format '{{.State.Running}}' "$bench_container")" != true ]]; then break; fi
  sleep 2
done
[[ "$ready" == true ]] || { echo "Android did not complete boot within the deadline." >&2; exit 1; }

printf 'Container: %s\nNetwork: %s\nADB_SERVER_SOCKET=tcp:%s:5037\nSerial: emulator-5554\n' \
  "$bench_container" "$bench_network" "$bench_container"
docker exec "$bench_container" adb -s emulator-5554 shell getprop ro.build.fingerprint
docker exec "$bench_container" adb -s emulator-5554 shell pm path com.android.chrome
echo "No ports are published. Attach the worker to the bench network."
echo "Chrome is preinstalled in this observation image; record its version before running WF01."
