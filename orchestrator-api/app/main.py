from __future__ import annotations

import io
import os
import re
import shlex
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Literal
from uuid import uuid4

import docker
import httpx
from docker.errors import DockerException, NotFound
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .run_routes import router as run_router
from .auth import auth_enabled
from .auth_routes import AuthMiddleware, router as auth_router
from .console_routes import router as console_router
from .user_routes import router as user_router
from .user_security_routes import router as user_security_router
from .profile_routes import router as profile_router
from .automation_routes import router as automation_router
from .monitor_routes import router as monitor_router
from .screen_routes import router as screen_router
from .emulator_routes import router as emulator_router
from .self_security import router as self_security_router
from .chatgpt_routes import router as chatgpt_router
from .chatgpt_process import close_manager


APP_NAME = os.getenv("APP_NAME", "Emulytix Orchestrator API")
AGENT_SERVICE_URL = os.getenv("AGENT_SERVICE_URL", "http://agent-service:8011")
ANDROID_STREAM_URL = os.getenv("ANDROID_STREAM_URL", "http://android-runtime:6080")
PUBLIC_ANDROID_STREAM_URL = os.getenv(
    "PUBLIC_ANDROID_EMBED_URL",
    os.getenv("PUBLIC_ANDROID_STREAM_URL", "http://localhost:6080/vnc.html?autoconnect=1&resize=scale&show_dot=1"),
)
ANDROID_STREAM_PROVIDER = os.getenv("ANDROID_STREAM_PROVIDER", "novnc")
ANDROID_RUNTIME_CONTAINER = os.getenv("ANDROID_RUNTIME_CONTAINER", "emulytix-android-runtime")
STORAGE_ROOT = Path(os.getenv("EMULYTIX_STORAGE_ROOT", "/storage"))
ADB_REMOTE_DIR = "/tmp/emulytix"
EMULYTIX_RUNTIME_MODE = os.getenv("EMULYTIX_RUNTIME_MODE", "docker")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def ensure_storage_root() -> None:
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)


def apks_dir(session_id: str) -> Path:
    path = STORAGE_ROOT / "apks" / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def screenshots_dir(session_id: str) -> Path:
    path = STORAGE_ROOT / "screenshots" / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned or "upload.apk"


def docker_client() -> docker.DockerClient:
    return docker.from_env()


def local_exec(command: str, binary: bool = False) -> str | bytes:
    try:
        result = subprocess.run(
            ["sh", "-lc", command],
            capture_output=True,
            timeout=45,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail=f"Local runtime command timed out: {command}") from exc

    output = result.stdout if binary else result.stdout.decode("utf-8", errors="ignore").strip()
    stderr = result.stderr.decode("utf-8", errors="ignore").strip()
    if result.returncode != 0:
        raise HTTPException(status_code=409, detail=stderr or (output if isinstance(output, str) else "Local runtime command failed."))
    return output


def local_visual_stream_available() -> bool:
    stream_url = PUBLIC_ANDROID_STREAM_URL or "http://127.0.0.1:6080/"

    try:
        parsed = urlparse(stream_url)
        target = parsed._replace(netloc="127.0.0.1:6080").geturl() if parsed.scheme in {"http", "https"} else "http://127.0.0.1:6080/"
    except ValueError:
        target = "http://127.0.0.1:6080/"

    try:
        with httpx.Client(timeout=2.0, follow_redirects=True) as client:
            response = client.get(target)
            return response.status_code < 500
    except httpx.HTTPError:
        return False


def local_emulator_process_running() -> bool:
    result = subprocess.run(
        ["sh", "-lc", "pgrep -f 'qemu-system.*android|qemu-system-x86_64 @' >/dev/null 2>&1"],
        capture_output=True,
        timeout=5,
        check=False,
    )
    return result.returncode == 0


def local_runtime_status() -> dict[str, Any]:
    try:
        output = subprocess.run(
            ["sh", "-lc", "adb devices"],
            capture_output=True,
            timeout=10,
            check=False,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "container_name": "local-runtime",
            "container_exists": True,
            "running": False,
            "status": "adb-timeout",
            "reason": "ADB did not respond in time.",
            "embed_url": None,
            "stream_provider": ANDROID_STREAM_PROVIDER,
        }

    online_devices = []
    device_states: list[dict[str, str]] = []
    for line in output.stdout.splitlines():
        if "\t" not in line:
            continue
        device_id, state = line.split("\t", 1)
        normalized_state = state.strip()
        device_states.append({"id": device_id.strip(), "state": normalized_state})
        if normalized_state == "device":
            online_devices.append(device_id.strip())

    if online_devices:
        return {
            "available": True,
            "container_name": "local-runtime",
            "container_exists": True,
            "running": True,
            "status": "running",
            "reason": None,
            "embed_url": PUBLIC_ANDROID_STREAM_URL,
            "devices": online_devices,
            "device_states": device_states,
            "visual_available": True,
            "stream_provider": ANDROID_STREAM_PROVIDER,
        }

    visual_available = local_visual_stream_available()
    emulator_running = local_emulator_process_running()
    booting_reason = "Android runtime is starting. The visual stream is available, but ADB is not ready yet."
    if any(device["state"] == "offline" for device in device_states):
        booting_reason = "Android runtime is booting. The visual stream is available, but ADB still reports the device as offline."

    if visual_available or emulator_running or device_states:
        return {
            "available": False,
            "container_name": "local-runtime",
            "container_exists": True,
            "running": True,
            "status": "booting",
            "reason": booting_reason,
            "embed_url": PUBLIC_ANDROID_STREAM_URL if visual_available else None,
            "devices": online_devices,
            "device_states": device_states,
            "visual_available": visual_available,
            "stream_provider": ANDROID_STREAM_PROVIDER,
        }

    if not os.path.exists("/dev/kvm"):
        return {
            "available": False,
            "container_name": "local-runtime",
            "container_exists": True,
            "running": False,
            "status": "missing-kvm",
            "reason": "Local Android runtime mode requires /dev/kvm, but this device is not exposed.",
            "embed_url": None,
            "device_states": device_states,
            "visual_available": False,
            "stream_provider": ANDROID_STREAM_PROVIDER,
        }

    return {
        "available": False,
        "container_name": "local-runtime",
        "container_exists": True,
        "running": False,
        "status": "starting",
        "reason": "Local Android runtime mode is enabled, but no ADB device is attached yet.",
        "embed_url": None,
        "device_states": device_states,
        "visual_available": False,
        "stream_provider": ANDROID_STREAM_PROVIDER,
    }


def get_runtime_container() -> Any | None:
    try:
        return docker_client().containers.get(ANDROID_RUNTIME_CONTAINER)
    except NotFound:
        return None
    except DockerException:
        return None


def get_runtime_status() -> dict[str, Any]:
    if EMULYTIX_RUNTIME_MODE == "local":
        return local_runtime_status()

    container = get_runtime_container()
    if container is None:
        return {
            "available": False,
            "container_name": ANDROID_RUNTIME_CONTAINER,
            "container_exists": False,
            "running": False,
            "status": "missing",
            "reason": "Android runtime container is not running. On this server, /dev/kvm is not exposed, so the emulator profile cannot start here.",
            "embed_url": None,
            "visual_available": False,
            "stream_provider": ANDROID_STREAM_PROVIDER,
        }

    container.reload()
    running = container.status == "running"
    return {
        "available": running,
        "container_name": ANDROID_RUNTIME_CONTAINER,
        "container_exists": True,
        "running": running,
        "status": container.status,
        "reason": None if running else f"Android runtime container exists but is not running: {container.status}.",
        "embed_url": PUBLIC_ANDROID_STREAM_URL if running else None,
        "visual_available": running,
        "stream_provider": ANDROID_STREAM_PROVIDER,
    }


def runtime_capabilities() -> dict[str, Any]:
    return {
        "runtime_mode": EMULYTIX_RUNTIME_MODE,
        "docker_socket_available": os.path.exists("/var/run/docker.sock"),
        "storage_root": str(STORAGE_ROOT),
        "android_stream_provider": ANDROID_STREAM_PROVIDER,
        "android_runtime": get_runtime_status(),
    }


def require_runtime_container() -> Any:
    if EMULYTIX_RUNTIME_MODE == "local":
        runtime = get_runtime_status()
        if not runtime["available"]:
            raise HTTPException(status_code=409, detail=runtime["reason"])
        return None

    container = get_runtime_container()
    if container is None:
        raise HTTPException(status_code=409, detail=get_runtime_status()["reason"])
    container.reload()
    if container.status != "running":
        raise HTTPException(
            status_code=409,
            detail=f"Android runtime container is not running: {container.status}",
        )
    return container


def runtime_exec(command: str) -> str:
    require_legacy_control()
    if EMULYTIX_RUNTIME_MODE == "local":
        output = local_exec(command)
        assert isinstance(output, str)
        return output

    container = require_runtime_container()
    result = container.exec_run(["sh", "-lc", command], stdout=True, stderr=True)
    output = result.output.decode("utf-8", errors="ignore").strip()
    if result.exit_code != 0:
        raise HTTPException(status_code=409, detail=output or "Android runtime command failed.")
    return output


def runtime_exec_binary(command: str) -> bytes:
    require_legacy_control()
    if EMULYTIX_RUNTIME_MODE == "local":
        output = local_exec(command, binary=True)
        assert isinstance(output, bytes)
        return output

    container = require_runtime_container()
    result = container.exec_run(["sh", "-lc", command], stdout=True, stderr=True)
    output = result.output or b""
    if result.exit_code != 0:
        raise HTTPException(
            status_code=409,
            detail=output.decode("utf-8", errors="ignore") or "Android runtime binary command failed.",
        )
    return output


def require_legacy_control() -> None:
    if os.getenv("EMULYTIX_LEGACY_CONTROL_ENABLED", "true").lower() not in {"true", "1", "yes"}:
        raise HTTPException(409, "Legacy Android control is disabled while managed workers are enabled")


def adb(command: str) -> str:
    runtime = get_runtime_status()
    if not runtime["available"]:
        raise HTTPException(status_code=409, detail=runtime["reason"])
    return runtime_exec(f"adb wait-for-device >/dev/null 2>&1 && {command}")


def adb_shell(command: str) -> str:
    return adb(f"adb shell {command}")


def list_apk_files(session_id: str) -> list[dict[str, Any]]:
    files = []
    for apk in sorted(apks_dir(session_id).glob("*.apk"), key=lambda path: path.stat().st_mtime, reverse=True):
        stat = apk.stat()
        files.append(
            {
                "name": apk.name,
                "size": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                "path": str(apk),
            }
        )
    return files


def latest_apk_path(session_id: str) -> Path:
    apks = list(apks_dir(session_id).glob("*.apk"))
    if not apks:
        raise HTTPException(status_code=404, detail="No APK uploaded for this session.")
    return max(apks, key=lambda path: path.stat().st_mtime)


def copy_to_runtime(local_path: Path, remote_name: str) -> str:
    if EMULYTIX_RUNTIME_MODE == "local":
        local_exec(f"mkdir -p {ADB_REMOTE_DIR}")
        target = Path(ADB_REMOTE_DIR) / remote_name
        target.write_bytes(local_path.read_bytes())
        return str(target)

    container = require_runtime_container()
    runtime_exec(f"mkdir -p {ADB_REMOTE_DIR}")

    archive = io.BytesIO()
    data = local_path.read_bytes()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        info = tarfile.TarInfo(name=remote_name)
        info.size = len(data)
        info.mtime = int(datetime.now(UTC).timestamp())
        tar.addfile(info, io.BytesIO(data))
    archive.seek(0)

    ok = container.put_archive(ADB_REMOTE_DIR, archive.read())
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to copy APK into Android runtime container.")
    return f"{ADB_REMOTE_DIR}/{remote_name}"


def list_installed_packages() -> list[str]:
    output = adb_shell("pm list packages")
    packages = []
    for line in output.splitlines():
        if line.startswith("package:"):
            packages.append(line.removeprefix("package:").strip())
    return packages


def escape_adb_text(value: str) -> str:
    escaped = value.replace(" ", "%s")
    return shlex.quote(escaped)


class SessionCreateRequest(BaseModel):
    name: str = Field(default="New Emulytix Session")


class SessionRecord(BaseModel):
    id: str
    name: str
    status: Literal["created", "running", "stopped", "deleted"]
    created_at: str
    updated_at: str
    runtime: str
    last_prompt: str | None = None
    selected_model: str | None = None


class InstallApkRequest(BaseModel):
    package_name: str | None = None
    file_name: str | None = None
    source: str = Field(default="upload")


class DeviceTapRequest(BaseModel):
    x: int
    y: int


class DeviceTextRequest(BaseModel):
    text: str


class DeviceKeyRequest(BaseModel):
    keycode: str


class OpenAppRequest(BaseModel):
    package_name: str


class UninstallAppRequest(BaseModel):
    package_name: str


class ChatRequest(BaseModel):
    prompt: str
    model: str = "gpt-5.4"
    reasoning_effort: Literal["low", "medium", "high"] = "medium"
    execute: bool = True
    openai_api_key: str | None = None


class ActionResponse(BaseModel):
    status: str
    detail: str
    session_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanRequest(BaseModel):
    session_id: str
    prompt: str
    model: str
    reasoning_effort: Literal["low", "medium", "high"] = "medium"
    available_tools: list[str] = Field(default_factory=list)
    available_apks: list[str] = Field(default_factory=list)
    runtime_available: bool = False
    installed_packages: list[str] = Field(default_factory=list)
    openai_api_key: str | None = None


app = FastAPI(
    title=APP_NAME,
    description="API de pilotage pour sessions Android Emulytix.",
    version="0.2.0",
)

app.include_router(run_router)
app.include_router(auth_router)
app.include_router(console_router)
app.include_router(user_router)
app.include_router(user_security_router)
app.include_router(profile_router)
app.include_router(automation_router)
app.include_router(monitor_router)
app.include_router(screen_router)
app.include_router(emulator_router)
app.include_router(self_security_router)
app.include_router(chatgpt_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("EMULYTIX_PUBLIC_ORIGIN", "")] if auth_enabled() else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)

SESSIONS: dict[str, SessionRecord] = {}


def get_session(session_id: str) -> SessionRecord:
    session = SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def action_response(session_id: str, detail: str, status: str = "accepted", **metadata: Any) -> ActionResponse:
    return ActionResponse(status=status, detail=detail, session_id=session_id, metadata=metadata)


def install_apk_internal(session_id: str, payload: InstallApkRequest) -> ActionResponse:
    get_session(session_id)
    selected = payload.file_name
    apk_path = apks_dir(session_id) / selected if selected else latest_apk_path(session_id)
    if not apk_path.exists():
        raise HTTPException(status_code=404, detail=f"APK '{apk_path.name}' not found for this session.")

    remote_path = copy_to_runtime(apk_path, apk_path.name)
    output = adb(f"adb install -r {shlex.quote(remote_path)}")
    return action_response(
        session_id,
        f"APK installed from {apk_path.name}.",
        command_output=output,
        file_name=apk_path.name,
    )


def uninstall_app_internal(session_id: str, payload: UninstallAppRequest) -> ActionResponse:
    get_session(session_id)
    output = adb(f"adb uninstall {shlex.quote(payload.package_name)}")
    return action_response(
        session_id,
        f"Uninstall requested for package '{payload.package_name}'.",
        command_output=output,
        package_name=payload.package_name,
    )


def tap_device_internal(session_id: str, payload: DeviceTapRequest) -> ActionResponse:
    get_session(session_id)
    adb_shell(f"input tap {payload.x} {payload.y}")
    return action_response(session_id, f"Tap executed at ({payload.x}, {payload.y}).", x=payload.x, y=payload.y)


def type_text_internal(session_id: str, payload: DeviceTextRequest) -> ActionResponse:
    get_session(session_id)
    adb_shell(f"input text {escape_adb_text(payload.text)}")
    return action_response(session_id, f"Text sent to device.", text=payload.text)


def send_key_internal(session_id: str, payload: DeviceKeyRequest) -> ActionResponse:
    get_session(session_id)
    adb_shell(f"input keyevent {shlex.quote(payload.keycode)}")
    return action_response(session_id, f"Key event '{payload.keycode}' sent.", keycode=payload.keycode)


def open_app_internal(session_id: str, payload: OpenAppRequest) -> ActionResponse:
    get_session(session_id)
    output = adb_shell(
        f"monkey -p {shlex.quote(payload.package_name)} -c android.intent.category.LAUNCHER 1"
    )
    return action_response(
        session_id,
        f"Open app requested for '{payload.package_name}'.",
        command_output=output,
        package_name=payload.package_name,
    )


def create_screenshot_internal(session_id: str) -> ActionResponse:
    get_session(session_id)
    file_name = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.png"
    target = screenshots_dir(session_id) / file_name
    data = runtime_exec_binary("adb wait-for-device >/dev/null 2>&1 && adb exec-out screencap -p")
    target.write_bytes(data)
    return action_response(
        session_id,
        "Screenshot captured.",
        file_name=file_name,
        path=str(target),
    )


def delete_apk_internal(session_id: str, file_name: str) -> ActionResponse:
    get_session(session_id)
    target = apks_dir(session_id) / sanitize_filename(file_name)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"APK '{file_name}' not found.")
    target.unlink()
    return action_response(session_id, f"APK '{target.name}' deleted.", file_name=target.name)


def execute_step(session_id: str, step: dict[str, Any]) -> dict[str, Any]:
    tool = step.get("tool")
    args = step.get("args", {})

    if tool == "install_latest_apk":
        result = install_apk_internal(session_id, InstallApkRequest(file_name=args.get("file_name")))
    elif tool == "install_apk":
        result = install_apk_internal(session_id, InstallApkRequest(file_name=args.get("file_name")))
    elif tool == "uninstall_package":
        result = uninstall_app_internal(session_id, UninstallAppRequest(package_name=args["package_name"]))
    elif tool == "open_app":
        result = open_app_internal(session_id, OpenAppRequest(package_name=args["package_name"]))
    elif tool == "tap":
        result = tap_device_internal(session_id, DeviceTapRequest(x=args["x"], y=args["y"]))
    elif tool == "type_text":
        result = type_text_internal(session_id, DeviceTextRequest(text=args["text"]))
    elif tool == "press_key":
        result = send_key_internal(session_id, DeviceKeyRequest(keycode=args["keycode"]))
    elif tool == "screenshot":
        result = create_screenshot_internal(session_id)
    else:
        return {
            "tool": tool,
            "status": "skipped",
            "detail": f"Tool '{tool}' is not executable in orchestrator yet.",
        }

    return {
        "tool": tool,
        "status": result.status,
        "detail": result.detail,
        "metadata": result.metadata,
    }


def session_status_payload(session_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    runtime = get_runtime_status()
    packages: list[str] = []
    package_error: str | None = None

    if runtime["available"]:
        try:
            packages = list_installed_packages()
        except HTTPException as exc:
            package_error = str(exc.detail)
    else:
        package_error = runtime["reason"]

    return {
        "session": session.model_dump(),
        "runtime": runtime,
        "uploaded_apks": list_apk_files(session_id),
        "installed_packages": packages,
        "package_error": package_error,
    }


@app.on_event("startup")
def startup() -> None:
    ensure_storage_root()
    from .telemetry import service_heartbeat
    app.state.heartbeat = service_heartbeat(os.getenv("EMULYTIX_DATABASE_URL", ""), "api")
    app.state.heartbeat.__enter__()


@app.on_event("shutdown")
def stop_heartbeat():
    close_manager()
    if getattr(app.state, "heartbeat", None):
        app.state.heartbeat.__exit__(None, None, None)


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": app.title,
        "version": app.version,
        "docs_url": "/docs",
        "runtime_capabilities": runtime_capabilities(),
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "time": now_iso(), "runtime": get_runtime_status()}


@app.get("/runtime-capabilities")
def get_runtime_capabilities_endpoint() -> dict[str, Any]:
    return runtime_capabilities()


@app.get("/android/status")
def android_status() -> dict[str, Any]:
    return get_runtime_status()


@app.get("/ai/models")
async def ai_models() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{AGENT_SERVICE_URL}/models")
            response.raise_for_status()
            return response.json()
    except Exception:
        return {
            "default_model": "gpt-5.4",
            "configured": False,
            "models": [],
            "reason": "Agent service model catalog unavailable.",
        }


@app.post("/sessions", response_model=SessionRecord)
def create_session(payload: SessionCreateRequest) -> SessionRecord:
    session_id = str(uuid4())
    session = SessionRecord(
        id=session_id,
        name=payload.name,
        status="created",
        created_at=now_iso(),
        updated_at=now_iso(),
        runtime="budtmo/docker-android",
    )
    SESSIONS[session_id] = session
    return session


@app.get("/sessions", response_model=list[SessionRecord])
def list_sessions() -> list[SessionRecord]:
    return list(SESSIONS.values())


@app.get("/sessions/{session_id}", response_model=SessionRecord)
def read_session(session_id: str) -> SessionRecord:
    return get_session(session_id)


@app.get("/sessions/{session_id}/status")
def get_session_status(session_id: str) -> dict[str, Any]:
    return session_status_payload(session_id)


@app.post("/sessions/{session_id}/start", response_model=ActionResponse)
def start_session(session_id: str) -> ActionResponse:
    session = get_session(session_id)
    session.status = "running"
    session.updated_at = now_iso()
    runtime = get_runtime_status()
    detail = "Session marked as running."
    if not runtime["available"]:
        detail += f" Android runtime is unavailable: {runtime['reason']}"
    return action_response(session_id, detail)


@app.post("/sessions/{session_id}/stop", response_model=ActionResponse)
def stop_session(session_id: str) -> ActionResponse:
    session = get_session(session_id)
    session.status = "stopped"
    session.updated_at = now_iso()
    return action_response(session_id, "Session marked as stopped.")


@app.delete("/sessions/{session_id}", response_model=ActionResponse)
def delete_session(session_id: str) -> ActionResponse:
    session = get_session(session_id)
    session.status = "deleted"
    session.updated_at = now_iso()
    del SESSIONS[session_id]
    return action_response(session_id, "Session deleted.")


@app.get("/sessions/{session_id}/screen")
def get_session_screen(session_id: str) -> dict[str, Any]:
    get_session(session_id)
    runtime = get_runtime_status()
    return {
        "session_id": session_id,
        "embed_url": runtime["embed_url"],
        "mode": "iframe",
        "available": runtime["available"],
        "reason": runtime["reason"],
    }


@app.get("/sessions/{session_id}/apk")
def get_uploaded_apks(session_id: str) -> dict[str, Any]:
    get_session(session_id)
    return {"session_id": session_id, "files": list_apk_files(session_id)}


@app.post("/sessions/{session_id}/apk/upload", response_model=ActionResponse)
async def upload_apk(session_id: str, file: UploadFile = File(...)) -> ActionResponse:
    get_session(session_id)
    filename = sanitize_filename(file.filename or "upload.apk")
    target = apks_dir(session_id) / filename
    data = await file.read()
    target.write_bytes(data)
    return action_response(
        session_id,
        f"APK '{filename}' uploaded.",
        file_name=filename,
        size=len(data),
        path=str(target),
    )


@app.delete("/sessions/{session_id}/apk/{file_name}", response_model=ActionResponse)
def delete_apk(session_id: str, file_name: str) -> ActionResponse:
    return delete_apk_internal(session_id, file_name)


@app.post("/sessions/{session_id}/apk/install", response_model=ActionResponse)
def install_apk(session_id: str, payload: InstallApkRequest) -> ActionResponse:
    return install_apk_internal(session_id, payload)


@app.get("/sessions/{session_id}/packages")
def get_packages(session_id: str) -> dict[str, Any]:
    get_session(session_id)
    return {"session_id": session_id, "packages": list_installed_packages()}


@app.post("/sessions/{session_id}/device/tap", response_model=ActionResponse)
def tap_device(session_id: str, payload: DeviceTapRequest) -> ActionResponse:
    return tap_device_internal(session_id, payload)


@app.post("/sessions/{session_id}/device/text", response_model=ActionResponse)
def type_text(session_id: str, payload: DeviceTextRequest) -> ActionResponse:
    return type_text_internal(session_id, payload)


@app.post("/sessions/{session_id}/device/key", response_model=ActionResponse)
def send_key(session_id: str, payload: DeviceKeyRequest) -> ActionResponse:
    return send_key_internal(session_id, payload)


@app.post("/sessions/{session_id}/device/open-app", response_model=ActionResponse)
def open_app(session_id: str, payload: OpenAppRequest) -> ActionResponse:
    return open_app_internal(session_id, payload)


@app.post("/sessions/{session_id}/device/uninstall-app", response_model=ActionResponse)
def uninstall_app(session_id: str, payload: UninstallAppRequest) -> ActionResponse:
    return uninstall_app_internal(session_id, payload)


@app.post("/sessions/{session_id}/device/screenshot", response_model=ActionResponse)
def create_screenshot(session_id: str) -> ActionResponse:
    return create_screenshot_internal(session_id)


@app.get("/sessions/{session_id}/logs")
def session_logs(session_id: str) -> dict[str, Any]:
    get_session(session_id)
    runtime = get_runtime_status()
    return {
        "session_id": session_id,
        "entries": [
            {"time": now_iso(), "level": "info", "message": "Session scaffold created."},
            {
                "time": now_iso(),
                "level": "info",
                "message": "Android runtime is available." if runtime["available"] else runtime["reason"],
            },
        ],
    }


@app.post("/sessions/{session_id}/chat")
async def chat_with_agent(session_id: str, payload: ChatRequest) -> dict[str, Any]:
    session = get_session(session_id)
    session.last_prompt = payload.prompt
    session.selected_model = payload.model
    session.updated_at = now_iso()

    runtime = get_runtime_status()
    installed_packages: list[str] = []
    if runtime["available"]:
        try:
            installed_packages = list_installed_packages()
        except HTTPException:
            installed_packages = []

    plan_request = PlanRequest(
        session_id=session_id,
        prompt=payload.prompt,
        model=payload.model,
        reasoning_effort=payload.reasoning_effort,
        openai_api_key=payload.openai_api_key,
        available_tools=[
            "install_latest_apk",
            "install_apk",
            "uninstall_package",
            "open_app",
            "tap",
            "type_text",
            "press_key",
            "screenshot",
        ],
        available_apks=[item["name"] for item in list_apk_files(session_id)],
        runtime_available=runtime["available"],
        installed_packages=installed_packages,
    )

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(f"{AGENT_SERVICE_URL}/plan", json=plan_request.model_dump())
            response.raise_for_status()
            plan = response.json()
    except Exception as exc:
        plan = {
            "summary": "Agent unavailable, fallback response generated by orchestrator.",
            "provider": "orchestrator-fallback",
            "steps": [{"tool": "manual_review", "args": {"note": payload.prompt}}],
            "error": str(exc),
        }

    execution: list[dict[str, Any]] = []
    if payload.execute:
        for step in plan.get("steps", []):
            try:
                execution.append(execute_step(session_id, step))
            except HTTPException as exc:
                execution.append(
                    {
                        "tool": step.get("tool"),
                        "status": "error",
                        "detail": str(exc.detail),
                    }
                )

    return {
        "session_id": session_id,
        "message": "Prompt received.",
        "runtime": runtime,
        "plan": plan,
        "execution": execution,
    }
