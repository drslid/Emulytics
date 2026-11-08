"""Bounded, immutable local APK imports; no remote download or client-chosen path."""

import hashlib
import logging
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import tempfile
import time
from uuid import UUID, uuid4
import zipfile

from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

MAX_APK_BYTES = 128 * 1024 * 1024
logger = logging.getLogger(__name__)


def discard_rejected_import(metadata: dict) -> bool:
    """Remove only this request's verified artifact after a definite catalogue rollback."""
    try:
        root = Path(os.environ['EMULYTIX_APK_ROOT']).resolve(strict=True)
        filename = str(UUID(metadata['id'])) + '.apk'
        if metadata['filename'] != filename:
            raise ValueError()
        target = root / filename
        with os.fdopen(os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as handle:
            owned = os.fstat(handle.fileno())
            if (not stat.S_ISREG(owned.st_mode) or owned.st_uid != os.getuid()
                    or owned.st_size != metadata['size_bytes'] or not 1 <= owned.st_size <= MAX_APK_BYTES
                    or hashlib.file_digest(handle, 'sha256').hexdigest() != metadata['sha256']):
                raise ValueError()
            current = target.stat(follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino):
                raise ValueError()
            target.unlink()
        return True
    except (KeyError, TypeError, ValueError, OSError):
        logger.warning('Rejected APK cleanup could not be verified; artifact retained')
        return False


def _badging(path: Path) -> str:
    process = subprocess.Popen(['aapt', 'dump', 'badging', str(path)], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        output = bytearray()
        deadline = time.monotonic() + 10
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError('APK inspection timed out')
                if not selector.select(min(remaining, 0.1)):
                    continue
                chunk = os.read(process.stdout.fileno(), 65_536)
                if not chunk:
                    break
                if len(output) + len(chunk) > 1_048_576:
                    raise ValueError('APK manifest output exceeds its limit')
                output.extend(chunk)
        if process.wait(timeout=max(0.01, deadline-time.monotonic())) != 0:
            raise ValueError('Invalid APK manifest')
        return output.decode('utf-8', 'replace')
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)
        process.stdout.close()


def inspect_apk(path: Path) -> tuple[str, str | None]:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if (len(entries) > 50_000 or 'AndroidManifest.xml' not in archive.namelist()
                    or sum(entry.file_size for entry in entries) > 1024 * 1024 * 1024
                    or any(entry.flag_bits & 1 for entry in entries)):
                raise ValueError('Invalid APK archive')
        badging = _badging(path)
        package = re.search(r"^package: name='([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)'", badging, re.M)
        if package is None or len(package[1]) > 200 or re.search(r"^package:.*\bsplit='", badging, re.M):
            raise ValueError('A standalone APK is required')
        label = re.search(r"^application-label:'([^'\r\n]{1,160})'", badging, re.M)
        return package[1], label[1] if label else None
    except (ValueError, zipfile.BadZipFile, subprocess.TimeoutExpired):
        raise HTTPException(422, 'A compatible standalone APK is required') from None
    except OSError:
        raise HTTPException(503, 'APK inspection unavailable') from None


async def ingest_apk(file: UploadFile, name: str | None = None) -> dict:
    if not file.filename or not file.filename.lower().endswith('.apk'):
        raise HTTPException(422, 'A standalone .apk file is required')
    label = name.strip() if name else None
    if label is not None and (not label or len(label) > 160 or any(ord(c) < 32 for c in label)):
        raise HTTPException(422, 'Invalid application name')
    configured = os.getenv('EMULYTIX_APK_ROOT')
    if not configured:
        raise HTTPException(503, 'APK storage unavailable')
    root = Path(configured).resolve()
    root.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        digest, size = hashlib.sha256(), 0
        with tempfile.NamedTemporaryFile(dir=root, prefix='.import-', delete=False) as output:
            temporary = Path(output.name)
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_APK_BYTES:
                    raise HTTPException(413, 'APK exceeds 128 MiB')
                digest.update(chunk)
                output.write(chunk)
        package, manifest_label = await run_in_threadpool(inspect_apk, temporary)
        identity = str(uuid4())
        filename = identity + '.apk'
        os.replace(temporary, root / filename)
        temporary = None
        return {'id': identity, 'filename': filename, 'sha256': digest.hexdigest(),
                'package_name': package, 'name': label or manifest_label or package, 'size_bytes': size}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        await file.close()
