"""Resolve and verify the stable vanilla APK distributed by Aurora OSS."""

from dataclasses import dataclass
import json
import re
from time import monotonic

from fastapi import HTTPException
import httpx

from .apk_catalog import ExpectedApk, MAX_APK_BYTES, download_store_apk


ORIGIN = 'https://auroraoss.com'
INDEX_URL = ORIGIN + '/api/files'
DIRECTORY = '/downloads/AuroraStore/Release'
MIME_TYPE = 'application/vnd.android.package-archive'
PACKAGE_NAME = 'com.aurora.store'
# Published on https://auroraoss.com/aurora-store and the Aurora OSS repository.
SIGNER_SHA1 = '944275d7598bc03e488506064225a71990a22202'
SIGNER_SHA256 = '4c626157ad02bda3401a7263555f68a79663fc3e13a4d4369a12570941aa280f'
VERSION = r'(?:0|[1-9][0-9]{0,5})(?:\.(?:0|[1-9][0-9]{0,5})){2}'
MAX_INDEX_BYTES = 1024 * 1024
INDEX_TIMEOUT_SECONDS = 12


class AuroraUnavailable(RuntimeError):
    """The official release index or download is unavailable."""


class AuroraIncompatible(RuntimeError):
    """The official APK does not pass the managed emulator's checks."""


@dataclass(frozen=True, slots=True)
class Release:
    version_name: str
    size_bytes: int

    @property
    def url(self) -> str:
        return f'{ORIGIN}{DIRECTORY}/AuroraStore-{self.version_name}.apk'


def _read_index() -> object:
    body = bytearray()
    deadline = monotonic() + INDEX_TIMEOUT_SECONDS
    try:
        with httpx.stream('GET', INDEX_URL, timeout=INDEX_TIMEOUT_SECONDS, trust_env=False, follow_redirects=False,
                          headers={'Accept': 'application/json', 'Accept-Encoding': 'identity'}) as response:
            response.raise_for_status()
            if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                raise ValueError('Aurora OSS index used unexpected content encoding')
            for chunk in response.iter_bytes():
                if len(body) + len(chunk) > MAX_INDEX_BYTES or monotonic() >= deadline:
                    raise ValueError('Aurora OSS index exceeded its limit')
                body.extend(chunk)
        return json.loads(body)
    except (httpx.HTTPError, ValueError, RecursionError) as exc:
        raise AuroraUnavailable('Aurora OSS index unavailable') from exc


def _entries(directory: object) -> list[dict]:
    if isinstance(directory, dict) and directory.get('isDirectory') is True:
        entries = directory.get('contents')
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)]
    return []


def _select_release(index: object) -> Release:
    store = next((entry for entry in _entries(index) if entry.get('path') == '/downloads/AuroraStore'), None)
    stable = next((entry for entry in _entries(store) if entry.get('path') == DIRECTORY), None)
    releases = []
    for entry in _entries(stable):
        filename, size = entry.get('name'), entry.get('size')
        if not isinstance(filename, str) or entry.get('isDirectory') is not False:
            continue
        version = re.fullmatch(rf'AuroraStore-({VERSION})\.apk', filename)
        if (version is None or entry.get('path') != f'{DIRECTORY}/{filename}'
                or entry.get('mimeType') != MIME_TYPE or type(size) is not int or size <= 0):
            continue
        releases.append(Release(version[1], size))
    if not releases:
        raise AuroraUnavailable('Aurora OSS vanilla APK is missing')
    latest = max(releases, key=lambda release: tuple(map(int, release.version_name.split('.'))))
    if latest.size_bytes > MAX_APK_BYTES:
        raise AuroraIncompatible('Latest Aurora Store APK exceeds the size limit')
    return latest


def find_latest_release() -> Release:
    return _select_release(_read_index())


def download_release(release: Release) -> dict:
    if (re.fullmatch(VERSION, release.version_name) is None
            or type(release.size_bytes) is not int or not 1 <= release.size_bytes <= MAX_APK_BYTES):
        raise AuroraIncompatible('Invalid Aurora Store release')
    expected = ExpectedApk(PACKAGE_NAME, None, None, release.size_bytes, signer_sha1=SIGNER_SHA1,
                           signer_sha256=SIGNER_SHA256, version_name=release.version_name)
    try:
        return download_store_apk(release.url, f'Aurora Store ({release.version_name})', expected)
    except HTTPException as exc:
        if exc.status_code in {413, 422}:
            raise AuroraIncompatible('Latest Aurora Store APK failed compatibility or signature verification') from exc
        raise AuroraUnavailable('Aurora Store APK could not be downloaded or verified') from exc
