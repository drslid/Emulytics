"""Search the public F-Droid repository and import a specific, verified APK."""

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import tempfile
from threading import Lock
from time import monotonic
import unicodedata

from fastapi import HTTPException
import httpx
import ijson

from .apk_catalog import ExpectedApk, MAX_APK_BYTES, PACKAGE_NAME_PATTERN, ingest_apk_chunks


REPOSITORY = 'https://f-droid.org/repo'
INDEX_URL = REPOSITORY + '/index-v2.json'
MAX_INDEX_BYTES = 128 * 1024 * 1024
CACHE_SECONDS = 60 * 60
RETRY_SECONDS = 10
SHA256_PATTERN = r'[a-f0-9]{64}'
EMULATOR_SDK = 29
EMULATOR_ABIS = ('x86_64', 'x86')


@dataclass(frozen=True)
class Release:
    apk: ExpectedApk
    filename: str
    version_name: str
    added_at: str

    def view(self) -> dict:
        return {'sha256': self.apk.sha256, 'version_name': self.version_name, 'version_code': self.apk.version_code,
                'added_at': self.added_at, 'size_bytes': self.apk.size_bytes}


@dataclass(frozen=True)
class Application:
    package_name: str
    name: str
    search_names: tuple[str, ...]
    releases: tuple[Release, ...]


_cache_lock = Lock()
_cached_apps: dict[str, Application] = {}
_cache_until = 0.0
_cache_etag: str | None = None


def _client() -> httpx.Client:
    return httpx.Client(timeout=10, follow_redirects=False)


def _text(value, limit: int) -> str:
    if not isinstance(value, str):
        return ''
    return ''.join(char if ord(char) >= 32 else ' ' for char in value[:limit]).strip()


def _search_text(value: str) -> str:
    return ''.join(char for char in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(char))


def _compatible(manifest: dict) -> bool:
    uses_sdk = manifest.get('usesSdk')
    minimum = uses_sdk.get('minSdkVersion') if isinstance(uses_sdk, dict) else None
    maximum = manifest.get('maxSdkVersion')
    abis = manifest.get('nativecode')
    return ((type(minimum) is not int or minimum <= EMULATOR_SDK)
            and (type(maximum) is not int or maximum >= EMULATOR_SDK)
            and (abis is None or isinstance(abis, list) and (not abis or any(abi in EMULATOR_ABIS for abi in abis))))


def _release(package_name: str, sha256: str, raw) -> Release | None:
    if not isinstance(raw, dict) or not re.fullmatch(SHA256_PATTERN, sha256):
        return None
    file, manifest, added = raw.get('file'), raw.get('manifest'), raw.get('added')
    if not isinstance(file, dict) or not isinstance(manifest, dict) or type(added) is not int or added < 1:
        return None
    if not _compatible(manifest):
        return None
    filename, size, version = file.get('name'), file.get('size'), manifest.get('versionCode')
    if not isinstance(filename, str) or not re.fullmatch(r'/[A-Za-z0-9_.+-]{1,240}\.apk', filename):
        return None
    if file.get('sha256') != sha256 or type(size) is not int or not 1 <= size <= MAX_APK_BYTES:
        return None
    if type(version) is not int or not 1 <= version <= 9_223_372_036_854_775_807:
        return None
    try:
        added_at = datetime.fromtimestamp(added / 1000, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    except (ValueError, OverflowError, OSError):
        return None
    return Release(ExpectedApk(package_name, version, sha256, size), filename,
                   _text(manifest.get('versionName'), 100) or str(version), added_at)


def _application(package_name: str, raw) -> Application | None:
    if len(package_name) > 200 or not re.fullmatch(PACKAGE_NAME_PATTERN, package_name) or not isinstance(raw, dict):
        return None
    metadata, versions = raw.get('metadata'), raw.get('versions')
    if not isinstance(metadata, dict) or not isinstance(versions, dict):
        return None
    releases = [item for sha256, raw in versions.items() if (item := _release(package_name, sha256, raw)) is not None]
    if not releases:
        return None
    names = metadata.get('name')
    titles = {locale: _text(name, 160) for locale, name in names.items()} if isinstance(names, dict) else {}
    title = titles.get('en-US') or titles.get('en') or next((name for name in titles.values() if name), package_name)
    search_names = tuple(dict.fromkeys(_search_text(name) for name in (package_name, title, *titles.values()) if name))
    releases.sort(key=lambda item: (item.apk.version_code, item.added_at, item.apk.sha256), reverse=True)
    return Application(package_name, title, search_names, tuple(releases))


def _timed_bytes(response: httpx.Response, deadline: float):
    for chunk in response.iter_bytes():
        if monotonic() > deadline:
            raise TimeoutError('F-Droid transfer exceeded its time limit')
        yield chunk


def _fetch_index(etag: str | None) -> tuple[dict[str, Application] | None, str | None]:
    deadline = monotonic() + 25
    headers = {'If-None-Match': etag} if etag else {}
    with _client() as client, client.stream('GET', INDEX_URL, headers=headers) as response:
        if etag and response.status_code == 304:
            return None, etag
        response.raise_for_status()
        with tempfile.TemporaryFile() as index:
            size = 0
            for chunk in _timed_bytes(response, deadline):
                size += len(chunk)
                if size > MAX_INDEX_BYTES:
                    raise ValueError('F-Droid index exceeds its size limit')
                index.write(chunk)
            index.seek(0)
            apps = {}
            for package_name, item in ijson.kvitems(index, 'packages'):
                app = _application(package_name, item)
                if app:
                    apps[package_name] = app
            if not apps:
                raise ValueError('F-Droid index has no APK applications')
    return apps, response.headers.get('etag')


def _catalogue() -> dict[str, Application]:
    global _cached_apps, _cache_until, _cache_etag
    if monotonic() >= _cache_until and _cache_lock.acquire(blocking=False):
        try:
            if monotonic() >= _cache_until:
                apps, etag = _fetch_index(_cache_etag)
                if apps is not None:
                    _cached_apps = apps
                _cache_etag = etag
                _cache_until = monotonic() + CACHE_SECONDS
        except (httpx.HTTPError, ijson.JSONError, OSError, ValueError):
            _cache_until = monotonic() + RETRY_SECONDS
        finally:
            _cache_lock.release()
    if not _cached_apps:
        raise HTTPException(503, 'F-Droid catalogue is temporarily unavailable', headers={'Retry-After': str(RETRY_SECONDS)})
    return _cached_apps


def search_applications(query: str) -> dict:
    query = _search_text(' '.join(query.split()))
    if len(query) < 2:
        return {'items': []}
    matches = []
    terms = query.split()
    for app in _catalogue().values():
        if not any(all(term in name for term in terms) for name in app.search_names):
            continue
        rank = 0 if query in app.search_names else 1 if any(name.startswith(query) for name in app.search_names) else 2
        matches.append((rank, app))
    matches.sort(key=lambda match: (match[0], match[1].name.casefold(), match[1].package_name))
    return {'items': [{'package_name': app.package_name, 'name': app.name,
                       'versions': [release.view() for release in app.releases]} for _, app in matches[:12]]}


def find_release(package_name: str, sha256: str) -> tuple[Application, Release]:
    app = _catalogue().get(package_name)
    release = next((item for item in app.releases if item.apk.sha256 == sha256), None) if app else None
    if app is None or release is None:
        raise HTTPException(404, 'Selected F-Droid APK is no longer available')
    return app, release


def import_application(app: Application, release: Release) -> dict:
    name = f'{app.name[:157-len(release.version_name)]} ({release.version_name})'
    deadline = monotonic() + 40
    try:
        with _client() as client, client.stream('GET', REPOSITORY + release.filename) as response:
            if response.status_code in {404, 410}:
                raise HTTPException(404, 'Selected F-Droid APK is no longer available')
            response.raise_for_status()
            return ingest_apk_chunks(_timed_bytes(response, deadline), name, expected=release.apk)
    except (httpx.HTTPError, TimeoutError):
        raise HTTPException(503, 'F-Droid download is temporarily unavailable') from None
