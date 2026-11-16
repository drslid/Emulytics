"""Bounded Aptoide metadata lookups for compatible standalone APKs."""

from dataclasses import dataclass
from datetime import datetime
import json
import re
from time import monotonic

from fastapi import HTTPException
import httpx

from .apk_catalog import MAX_APK_BYTES, PACKAGE_NAME_PATTERN
from .fdroid_catalog import EMULATOR_ABIS, EMULATOR_SDK


API_ROOT = 'https://ws75.aptoide.com/api/7/'
MAX_RESPONSE_BYTES = 1024 * 1024
SEARCH_LIMIT = 12
VERSION_LIMIT = 40
DETAIL_LIMIT = 8
MD5_PATTERN = r'[a-f0-9]{32}'
VERSION_ID_PATTERN = rf'[1-9][0-9]{{0,9}}:{MD5_PATTERN}'
SNAPCHAT_WEB_VERSION_ID = '64939361:4ed9778e0ae2db28bf01081a07535cb0'
# Published certificate fingerprints, independently matched to the publisher on APKMirror.
PUBLISHER_CERTIFICATES = {
    'com.linkedin.android': ('443cb997718d0ac5162888bae5e4724582862676',
                             '3b6a403ca91d56ab854517720203176640816d3f923f92cca16138f5cc3d0727'),
    'com.snapchat.android': ('49f6badb81d89a9e38d65de76f09355071bd67e7',
                             '2f1caafca1ed30d0b4e38863eefabea0e815711fa4cf79b822519a8259d95a58'),
}


@dataclass(frozen=True, slots=True)
class Release:
    id: str
    package_name: str
    name: str
    version_name: str
    version_code: int
    added_at: str
    size_bytes: int
    md5: str
    signer_sha1: str
    signer_sha256: str | None
    url: str

    def view(self) -> dict:
        result = {'id': self.id, 'version_name': self.version_name, 'version_code': self.version_code,
                  'added_at': self.added_at, 'size_bytes': self.size_bytes}
        if self.package_name == 'com.snapchat.android' and self.id == SNAPCHAT_WEB_VERSION_ID:
            # This exact APK uses Android Browser Helper’s Trusted Web Activity launcher.
            result['variant'] = 'web'
        return result


def _client() -> httpx.Client:
    return httpx.Client(follow_redirects=False, headers={'Accept': 'application/json', 'Accept-Encoding': 'identity'})


def _object(value) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value, limit: int) -> str:
    if not isinstance(value, str):
        return ''
    return ''.join(char if char.isprintable() else ' ' for char in value[:limit]).strip()


def _valid_package(package) -> bool:
    return isinstance(package, str) and len(package) <= 200 and re.fullmatch(PACKAGE_NAME_PATTERN, package) is not None


def _json(client: httpx.Client, endpoint: str, params: dict, deadline: float, *, optional: bool = False) -> dict:
    try:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError('Aptoide request exceeded its time limit')
        with client.stream('GET', API_ROOT + endpoint, params=params, timeout=min(4, remaining)) as response:
            if optional and response.status_code == 404:
                return {}
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > MAX_RESPONSE_BYTES or monotonic() >= deadline:
                    raise ValueError('Aptoide response exceeded its limit')
                data.extend(chunk)
        body = _object(json.loads(data))
        if _object(body.get('info')).get('status') != 'OK':
            raise ValueError('Invalid Aptoide response')
        return body
    except (httpx.HTTPError, TimeoutError, ValueError, RecursionError) as exc:
        raise HTTPException(503, 'Aptoide catalogue unavailable') from exc


def _rows(result, limit: int) -> list[dict]:
    return [row for row in result[:limit] if isinstance(row, dict)] if isinstance(result, list) else []


def search_applications(query: str) -> dict:
    query = query.strip()
    if not 2 <= len(query) <= 100:
        return {'items': []}
    with _client() as client:
        result = _json(client, 'apps/search', {'query': query, 'limit': SEARCH_LIMIT}, monotonic() + 8)
    items = {}
    for row in _rows(_object(result.get('datalist')).get('list'), SEARCH_LIMIT):
        package = row.get('package')
        if _valid_package(package) and package not in items:
            items[package] = {'package_name': package, 'name': _text(row.get('name'), 160) or package, 'versions': []}
    return {'items': list(items.values())}


def _file_compatible(file: dict) -> bool:
    hardware = _object(file.get('hardware'))
    sdk, cpus = hardware.get('sdk'), hardware.get('cpus')
    size = file.get('filesize')
    return (type(sdk) is int and 1 <= sdk <= EMULATOR_SDK and isinstance(cpus, list)
            and (not cpus or any(cpu in (*EMULATOR_ABIS, 'x86-64') for cpu in cpus))
            and type(size) is int and 1 <= size <= MAX_APK_BYTES
            and _object(file.get('malware')).get('rank') == 'TRUSTED')


def _release(meta: dict, package: str, app_id: int, expected_md5: str) -> Release | None:
    bundle = meta.get('aab')
    if (meta.get('package') != package or type(meta.get('id')) is not int or meta['id'] != app_id or 'aab' not in meta or 'obb' not in meta
            or meta['obb'] is not None):
        return None
    if bundle is not None and (_object(bundle).get('required_split_types') != [] or _object(bundle).get('splits') != []):
        return None
    file = _object(meta.get('file'))
    code, md5, url = file.get('vercode'), file.get('md5sum'), file.get('path')
    if not _file_compatible(file) or type(code) is not int or not 1 <= code <= 2**63 - 1 or md5 != expected_md5:
        return None
    path_pattern = (r'https://pool\.apk\.aptoide\.com/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/'
                    rf'[A-Za-z0-9_.-]{{1,200}}-{code}-{app_id}-{md5}\.apk')
    if not isinstance(url, str) or re.fullmatch(path_pattern, url) is None:
        return None
    signer = _object(file.get('signature')).get('sha1')
    signer_sha1 = signer.replace(':', '').lower() if isinstance(signer, str) else ''
    if not re.fullmatch(r'[a-f0-9]{40}', signer_sha1):
        return None
    trusted_signer, signer_sha256 = PUBLISHER_CERTIFICATES.get(package, (None, None))
    third_party = _object(_object(_object(file.get('malware')).get('reason')).get('thirdparty_validated'))
    if (trusted_signer is not None and signer_sha1 != trusted_signer
            or trusted_signer is None and third_party.get('store') != 'Google Play'):
        return None
    try:
        added_at = datetime.strptime(file['added'], '%Y-%m-%d %H:%M:%S').isoformat() + 'Z'
    except (KeyError, TypeError, ValueError):
        return None
    return Release(f'{app_id}:{md5}', package, _text(meta.get('name'), 160) or package,
                   _text(file.get('vername'), 100) or str(code), code, added_at, file['filesize'], md5,
                   signer_sha1, signer_sha256, url)


def _find_version(client: httpx.Client, package: str, app_id: int, md5: str, deadline: float) -> Release | None:
    result = _json(client, 'app/get', {'app_id': app_id, 'nodes': 'meta', 'aab': 1}, deadline, optional=True)
    meta = _object(_object(_object(result.get('nodes')).get('meta')).get('data'))
    return _release(meta, package, app_id, md5)


def list_versions(package: str) -> dict:
    if not _valid_package(package):
        raise HTTPException(422, 'Invalid package name')
    deadline = monotonic() + 20
    with _client() as client:
        result = _json(client, 'listAppVersions', {'package_name': package, 'limit': VERSION_LIMIT, 'aab': 0}, deadline)
        records = _rows(result.get('list'), VERSION_LIMIT)
        candidates = {}
        for row in records:
            file = _object(row.get('file'))
            app_id, md5 = row.get('id'), file.get('md5sum')
            if (row.get('package') == package and type(app_id) is int and 1 <= app_id < 10**10
                    and isinstance(md5, str) and re.fullmatch(MD5_PATTERN, md5) and _file_compatible(file)):
                # Prefer explicit x86 variants over rows describing just an AAB base APK.
                candidates[app_id] = (md5, bool(file['hardware']['cpus']))
        ordered = sorted(candidates, key=lambda app_id: not candidates[app_id][1])[:DETAIL_LIMIT]
        releases = [release for app_id in ordered
                    if (release := _find_version(client, package, app_id, candidates[app_id][0], deadline)) is not None]
    releases.sort(key=lambda release: (release.version_code, release.added_at), reverse=True)
    return {'versions': [release.view() for release in releases]}


def find_release(package: str, version_id: str) -> Release:
    if not _valid_package(package) or not re.fullmatch(VERSION_ID_PATTERN, version_id):
        raise HTTPException(422, 'Invalid Aptoide version')
    app_id, md5 = version_id.split(':')
    with _client() as client:
        release = _find_version(client, package, int(app_id), md5, monotonic() + 8)
    if release is None:
        raise HTTPException(404, 'Compatible Aptoide version not found')
    return release
