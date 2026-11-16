"""Bounded, immutable APK imports from uploads and trusted catalogues."""

from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
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
import httpx
from starlette.concurrency import run_in_threadpool

MAX_APK_BYTES = 128 * 1024 * 1024
PACKAGE_NAME_PATTERN = r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+'
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExpectedApk:
    package_name: str
    version_code: int
    sha256: str | None
    size_bytes: int
    md5: str | None = None
    signer_sha1: str | None = None
    signer_sha256: str | None = None


@contextmanager
def _verified_artifact(metadata: dict):
    root = Path(os.environ['EMULYTIX_APK_ROOT']).resolve(strict=True)
    filename = str(UUID(str(metadata['id']))) + '.apk'
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
        yield target


def application_artifact_valid(metadata: dict) -> bool:
    try:
        with _verified_artifact(metadata):
            return True
    except (KeyError, TypeError, ValueError, OSError):
        return False


def discard_rejected_import(metadata: dict) -> bool:
    """Remove only this request's verified artifact after definite non-publication."""
    try:
        with _verified_artifact(metadata) as target:
            target.unlink()
        return True
    except (KeyError, TypeError, ValueError, OSError):
        logger.warning('Rejected APK cleanup could not be verified; artifact retained')
        return False


def _apk_tool(arguments: list[str], *, timeout: float = 10) -> str:
    process = subprocess.Popen(arguments, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        output = bytearray()
        deadline = time.monotonic() + timeout
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


def _badging(path: Path) -> str:
    return _apk_tool(['aapt', 'dump', 'badging', str(path)])


def _verify_store_signer(path: Path, badging: str, expected: ExpectedApk) -> None:
    minimum = re.search(r"^sdkVersion:'([0-9]+)'", badging, re.M)
    maximum = re.search(r"^maxSdkVersion:'([0-9]+)'", badging, re.M)
    native = re.search(r"^native-code:([^\r\n]*)", badging, re.M)
    if ((minimum and int(minimum[1]) > 29)
            or (maximum and int(maximum[1]) < 29)
            or (native and not {'x86', 'x86_64'}.intersection(re.findall(r"'([^']+)'", native[1])))
            or re.search(r"^uses-split:", badging, re.M)
            or not re.search(r"^launchable-activity:", badging, re.M)):
        raise ValueError('APK is incompatible with Android 10 x86')
    signatures = _apk_tool(['apksigner', 'verify', '--print-certs', '--min-sdk-version', '29',
                            '--max-sdk-version', '29', str(path)], timeout=25)
    for algorithm, required in (('SHA-1', expected.signer_sha1), ('SHA-256', expected.signer_sha256)):
        digests = re.findall(rf"^Signer #\d+ certificate {algorithm} digest: ([0-9a-fA-F]+)$", signatures, re.M)
        if required is not None and [digest.lower() for digest in digests] != [required]:
            raise ValueError('APK publisher certificate differs from the store')


def inspect_apk(path: Path, expected: ExpectedApk | None = None) -> tuple[str, str | None]:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if (len(entries) > 50_000 or 'AndroidManifest.xml' not in archive.namelist()
                    or sum(entry.file_size for entry in entries) > 1024 * 1024 * 1024
                    or any(entry.flag_bits & 1 for entry in entries)):
                raise ValueError('Invalid APK archive')
        badging = _badging(path)
        package = re.search(rf"^package: name='({PACKAGE_NAME_PATTERN})'", badging, re.M)
        if package is None or len(package[1]) > 200 or re.search(r"^package:.*\bsplit='", badging, re.M):
            raise ValueError('A standalone APK is required')
        if expected is not None:
            version = re.search(r"^package:[^\r\n]*\bversionCode='([0-9]{1,20})'", badging, re.M)
            if package[1] != expected.package_name or version is None or int(version[1]) != expected.version_code:
                raise HTTPException(422, 'APK manifest does not match the selected version')
            if expected.signer_sha1 is not None:
                _verify_store_signer(path, badging, expected)
        label = re.search(r"^application-label:'([^'\r\n]{1,160})'", badging, re.M)
        return package[1], label[1] if label else None
    except (ValueError, zipfile.BadZipFile, subprocess.TimeoutExpired):
        raise HTTPException(422, 'A compatible standalone APK is required') from None
    except OSError:
        raise HTTPException(503, 'APK inspection unavailable') from None


def ingest_apk_chunks(chunks: Iterable[bytes], name: str | None = None, *, expected: ExpectedApk | None = None) -> dict:
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
        md5 = hashlib.md5(usedforsecurity=False) if expected and expected.md5 else None
        with tempfile.NamedTemporaryFile(dir=root, prefix='.import-', delete=False) as output:
            temporary = Path(output.name)
            for chunk in chunks:
                size += len(chunk)
                if size > MAX_APK_BYTES:
                    raise HTTPException(413, 'APK exceeds 128 MiB')
                if expected is not None and size > expected.size_bytes:
                    raise HTTPException(422, 'APK download does not match the selected version')
                digest.update(chunk)
                if md5 is not None:
                    md5.update(chunk)
                output.write(chunk)
        sha256 = digest.hexdigest()
        if expected is not None and (size != expected.size_bytes
                or (expected.sha256 is not None and sha256 != expected.sha256)
                or (md5 is not None and md5.hexdigest() != expected.md5)):
            raise HTTPException(422, 'APK download does not match the selected version')
        package, manifest_label = inspect_apk(temporary, expected)
        identity = str(uuid4())
        filename = identity + '.apk'
        os.replace(temporary, root / filename)
        temporary = None
        return {'id': identity, 'filename': filename, 'sha256': sha256,
                'package_name': package, 'name': label or manifest_label or package, 'size_bytes': size}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def download_store_apk(url: str, label: str, expected: ExpectedApk) -> dict:
    deadline = time.monotonic() + 65

    def chunks(response: httpx.Response):
        for chunk in response.iter_bytes():
            if time.monotonic() > deadline:
                raise TimeoutError
            yield chunk

    try:
        with httpx.stream('GET', url, timeout=10, trust_env=False, follow_redirects=False) as response:
            if response.status_code in {404, 410}:
                raise HTTPException(404, 'Selected APK is no longer available')
            response.raise_for_status()
            return ingest_apk_chunks(chunks(response), label, expected=expected)
    except (httpx.HTTPError, TimeoutError):
        raise HTTPException(503, 'APK download is temporarily unavailable') from None


async def ingest_apk(file: UploadFile, name: str | None = None) -> dict:
    try:
        if not file.filename or not file.filename.lower().endswith('.apk'):
            raise HTTPException(422, 'A standalone .apk file is required')
        chunks = iter(lambda: file.file.read(1024 * 1024), b'')
        return await run_in_threadpool(ingest_apk_chunks, chunks, name)
    finally:
        await file.close()
