"""On-demand, read-only Android display observations shared as atomic frame packets."""

import hashlib
import json
import logging
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

import fcntl
import psycopg

from .run_store import RunStore

logger = logging.getLogger(__name__)
MAGIC = b"EMULYTIX_SCREEN_V1\n"
PNG = b"\x89PNG\r\n\x1a\n"
MAX_PNG_BYTES = 16 * 1024 * 1024
MAX_PACKET_BYTES = MAX_PNG_BYTES + 4096
MAX_FRAME_AGE = 3.0
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


class ScreenUnavailable(ValueError):
    pass


def _name(device_id: str) -> str:
    if not isinstance(device_id, str) or not IDENTIFIER.fullmatch(device_id):
        raise ScreenUnavailable("Invalid screen identity")
    return hashlib.sha256(device_id.encode()).hexdigest()


def _directory(root: Path, *, create=False) -> Path:
    root = Path(root).resolve(strict=True)
    directory = root / "screens"
    if create:
        directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir() or directory.resolve(strict=True).parent != root:
        raise ScreenUnavailable("Invalid screen directory")
    return directory


def valid_png(data: bytes) -> bool:
    if not isinstance(data, bytes) or not 33 <= len(data) <= MAX_PNG_BYTES or not data.startswith(PNG):
        return False
    if data[8:16] != b"\x00\x00\x00\rIHDR":
        return False
    width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return 0 < width <= 16384 and 0 < height <= 16384


def write_frame(root: Path, device_id: str, image: bytes, *, captured_at=None) -> dict:
    if not valid_png(image):
        raise ScreenUnavailable("Invalid Android frame")
    directory = _directory(root, create=True)
    name = _name(device_id)
    metadata = {
        "device_id": device_id,
        "captured_at": (captured_at or datetime.now(timezone.utc)).isoformat(),
        "frame_id": str(uuid4()),
        "sha256": hashlib.sha256(image).hexdigest(),
    }
    target = directory / f"{name}.frame"
    if target.is_symlink():
        raise ScreenUnavailable("Invalid screen file")
    packet = MAGIC + json.dumps(metadata, separators=(",", ":")).encode() + b"\n" + image
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{name}-", dir=directory, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(packet)
            handle.flush()
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return metadata


def read_frame(root: Path, device_id: str, *, now=None) -> tuple[bytes, dict, float]:
    directory = _directory(root)
    descriptor = os.open(directory / f"{_name(device_id)}.frame", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ScreenUnavailable("Invalid screen file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            packet = handle.read(MAX_PACKET_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(packet) > MAX_PACKET_BYTES or not packet.startswith(MAGIC):
        raise ScreenUnavailable("Invalid screen packet")
    header, separator, image = packet[len(MAGIC):].partition(b"\n")
    if not separator or len(header) > 4096 or not valid_png(image):
        raise ScreenUnavailable("Invalid screen packet")
    try:
        metadata = json.loads(header)
        captured_at = datetime.fromisoformat(metadata["captured_at"])
        frame_id = metadata["frame_id"]
        if not isinstance(frame_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", frame_id):
            raise ValueError("Invalid frame ID")
        if captured_at.tzinfo is None or metadata["device_id"] != device_id:
            raise ValueError("Wrong frame identity")
        if hashlib.sha256(image).hexdigest() != metadata["sha256"]:
            raise ValueError("Invalid frame checksum")
        age = ((now or datetime.now(timezone.utc)) - captured_at).total_seconds()
        if not -1 <= age <= MAX_FRAME_AGE:
            raise ValueError("Stale frame")
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ScreenUnavailable("Screen is not current") from None
    return image, metadata, max(0.0, age)


def capture_android(serial: str, *, adb_binary="adb", adb_server_host=None) -> bytes:
    if not isinstance(serial, str) or not IDENTIFIER.fullmatch(serial):
        raise ScreenUnavailable("Invalid Android identity")
    # The Linux launcher also kills this read-only client when its worker exits.
    if adb_server_host is not None and not re.fullmatch(r'emulytix-managed-[a-f0-9]{32}', adb_server_host):
        raise ScreenUnavailable('Invalid managed ADB server')
    server = ['-H', adb_server_host, '-P', '5037'] if adb_server_host else []
    command = [sys.executable, str(Path(__file__).with_name("adb_child.py")), str(os.getpid()),
               adb_binary, *server, "-s", serial, "exec-out", "screencap", "-p"]
    process = None
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        image = bytearray()
        deadline = time.monotonic() + 3
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ScreenUnavailable("Android display timed out")
                if not selector.select(min(remaining, 0.1)):
                    continue
                chunk = os.read(process.stdout.fileno(), 65_536)
                if not chunk:
                    break
                if len(image) + len(chunk) > MAX_PNG_BYTES:
                    raise ScreenUnavailable("Android display exceeded frame limit")
                image.extend(chunk)
        if process.wait(timeout=max(0.01, deadline - time.monotonic())) != 0 or not valid_png(bytes(image)):
            raise ScreenUnavailable("Android display unavailable")
        return bytes(image)
    except (OSError, subprocess.SubprocessError):
        raise ScreenUnavailable("Android display unavailable") from None
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=1)
            if process.stdout:
                process.stdout.close()



class ScreenPublisher:
    def __init__(self, dsn, host_id, artifact_root, lock_root, *, capture=capture_android):
        self.store = RunStore(dsn)
        self.host_id = host_id
        self.artifact_root = Path(artifact_root)
        self.lock_root = Path(lock_root)
        self.capture = capture

    def publish_once(self, stopping=None) -> int:
        with self.store.connect() as connection:
            devices = connection.execute(
                "SELECT d.device_id,d.serial,m.id AS managed_id FROM live_screen_requests s JOIN devices d USING(device_id) "
                "LEFT JOIN managed_emulators m USING(device_id) "
                "WHERE s.expires_at>clock_timestamp() AND d.host_id=%s ORDER BY d.device_id LIMIT 100",
                (self.host_id,),
            ).fetchall()
        published = 0
        self.lock_root.mkdir(parents=True, exist_ok=True)
        for device in devices:
            if stopping is not None and stopping.is_set():
                break
            # A separate lock namespace never competes with the Android execution lease.
            name = _name(device["device_id"])
            descriptor = os.open(self.lock_root / f"screen-{name}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                with self.store.connect() as connection:
                    requested = connection.execute(
                        "SELECT 1 FROM live_screen_requests WHERE device_id=%s AND expires_at>clock_timestamp()",
                        (device["device_id"],),
                    ).fetchone()
                if not requested:
                    continue
                try:
                    captured_at = datetime.now(timezone.utc)
                    if device['managed_id']:
                        from .emulator_runtime import adb_server
                        image = self.capture(device['serial'], adb_server_host=adb_server({'id': device['managed_id']}))
                    else:
                        image = self.capture(device["serial"])
                    write_frame(self.artifact_root, device["device_id"], image, captured_at=captured_at)
                    published += 1
                except (ScreenUnavailable, OSError):
                    # The reader marks the previous frame stale, never a fabricated success.
                    logger.debug("screen.capture_unavailable")
            finally:
                os.close(descriptor)
        return published

    def run(self, stopped):
        while not stopped.is_set():
            started = time.monotonic()
            try:
                self.publish_once(stopped)
            except (psycopg.Error, OSError, ScreenUnavailable):
                logger.warning("screen.publisher_unavailable")
            stopped.wait(max(0.05, 0.5 - (time.monotonic() - started)))


@contextmanager
def live_screens(dsn, host_id, artifact_root, lock_root):
    stopped = threading.Event()
    publisher = ScreenPublisher(dsn, host_id, artifact_root, lock_root)
    thread = threading.Thread(target=publisher.run, args=(stopped,), daemon=True, name="live-screens")
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=4)
