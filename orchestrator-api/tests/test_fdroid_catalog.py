from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
from threading import Barrier
import zipfile

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

from app import apk_catalog, fdroid_catalog
from app.access import required_permission
from app.emulator_routes import router
from app.emulator_store import EmulatorStore


PACKAGE = 'org.example.notes'
APK_PATH = '/org.example.notes_12.apk'
ENDPOINT = '/console/applications/fdroid'


def apk_bytes():
    body = io.BytesIO()
    with zipfile.ZipFile(body, 'w') as archive:
        archive.writestr('AndroidManifest.xml', b'binary-manifest')
    return body.getvalue()


def entry(filename, digest, size, code, version=None):
    return {'added': 1_760_000_000_000, 'file': {'name': filename, 'sha256': digest, 'size': size},
            'manifest': {'versionCode': code, 'versionName': version}}


@pytest.fixture
def repository(tmp_path, monkeypatch):
    content = apk_bytes()
    digest = hashlib.sha256(content).hexdigest()
    newest, unsafe = 'a' * 64, 'b' * 64
    packages = {PACKAGE: {'metadata': {'name': {'en-US': 'Notes', 'fr': 'Carnét'}}, 'versions': {
        digest: entry(APK_PATH, digest, len(content), 12, '1.2'),
        newest: entry('/org.example.notes_13.apk', newest, len(content), 13),
        unsafe: entry('//somewhere.example/outside.apk', unsafe, len(content), 14, '1.4'),
    }}}
    requests = []

    def download(request):
        requests.append(request)
        if str(request.url) == fdroid_catalog.INDEX_URL:
            if request.headers.get('If-None-Match') == '"fdroid-index"':
                return httpx.Response(304)
            return httpx.Response(200, json={'packages': packages}, headers={'ETag': '"fdroid-index"'})
        if str(request.url) == fdroid_catalog.REPOSITORY + APK_PATH:
            return httpx.Response(200, content=content)
        return httpx.Response(302, headers={'Location': 'https://somewhere.example/outside.apk'})

    monkeypatch.setattr(fdroid_catalog, '_cache_until', 0.0)
    monkeypatch.setattr(fdroid_catalog, '_cache_etag', None)
    monkeypatch.setattr(fdroid_catalog, '_cached_apps', {})
    monkeypatch.setattr(fdroid_catalog, '_client', lambda: httpx.Client(transport=httpx.MockTransport(download)))
    monkeypatch.setenv('EMULYTIX_APK_ROOT', str(tmp_path))
    monkeypatch.setattr(apk_catalog, '_badging', lambda path: f"package: name='{PACKAGE}' versionCode='12'\n")
    return digest, packages[PACKAGE]['versions'], requests


def test_search_uses_localized_names_sorts_exact_versions_and_reuses_cache(repository, monkeypatch):
    digest, _, requests = repository
    result = fdroid_catalog.search_applications('carnet')
    assert result == fdroid_catalog.search_applications(PACKAGE)
    assert len(requests) == 1
    notes, = result['items']
    assert notes['name'] == 'Notes'
    assert [version['version_name'] for version in notes['versions']] == ['13', '1.2']
    assert notes['versions'][1]['sha256'] == digest
    assert notes['versions'][1]['added_at'] == '2025-10-09T08:53:20Z'

    monkeypatch.setattr(fdroid_catalog, '_cache_until', 0.0)
    assert fdroid_catalog.search_applications('notes') == result
    assert requests[-1].headers['If-None-Match'] == '"fdroid-index"'


@pytest.mark.parametrize('manifest', [
    {'nativecode': ['arm64-v8a', 'armeabi-v7a']},
    {'usesSdk': {'minSdkVersion': 30}},
    {'maxSdkVersion': 28},
])
def test_search_hides_releases_incompatible_with_managed_android(repository, manifest):
    digest, releases, _ = repository
    releases[digest]['manifest'].update(manifest)
    releases['a' * 64]['manifest']['nativecode'] = ['x86']
    item, = fdroid_catalog.search_applications('notes')['items']
    assert [release['version_code'] for release in item['versions']] == [13]


def test_concurrent_cache_refresh_returns_current_apps_or_fails_fast(repository, monkeypatch):
    _, _, requests = repository
    with fdroid_catalog._cache_lock:
        with pytest.raises(HTTPException) as loading:
            fdroid_catalog.search_applications('notes')
        assert loading.value.status_code == 503
    assert not requests

    expected = fdroid_catalog.search_applications('notes')
    monkeypatch.setattr(fdroid_catalog, '_cache_until', 0.0)
    with fdroid_catalog._cache_lock:
        assert fdroid_catalog.search_applications('notes') == expected
    assert len(requests) == 1


def test_download_deadline_checks_each_small_network_chunk(monkeypatch):
    class SmallChunks(httpx.SyncByteStream):
        def __iter__(self):
            yield b'a'
            yield b'b'

    timestamp = iter([1.0, 3.0])
    monkeypatch.setattr(fdroid_catalog, 'monotonic', lambda: next(timestamp))
    response = httpx.Response(200, stream=SmallChunks())
    chunks = fdroid_catalog._timed_bytes(response, deadline=2.0)
    assert next(chunks) == b'a'
    with pytest.raises(TimeoutError):
        next(chunks)


def test_import_uses_exact_catalogue_release_and_never_follows_redirects(repository, tmp_path):
    digest, _, requests = repository
    imported = fdroid_catalog.import_application(*fdroid_catalog.find_release(PACKAGE, digest))
    assert imported['package_name'] == PACKAGE
    assert imported['name'] == 'Notes (1.2)'
    assert (tmp_path / imported['filename']).read_bytes() == apk_bytes()
    assert str(requests[-1].url) == fdroid_catalog.REPOSITORY + APK_PATH

    with pytest.raises(HTTPException) as rejected:
        fdroid_catalog.import_application(*fdroid_catalog.find_release(PACKAGE, 'a' * 64))
    assert rejected.value.status_code == 503
    assert all(request.url.host == 'f-droid.org' for request in requests)


@pytest.mark.parametrize('mismatch', ['digest', 'package', 'version', 'size'])
def test_import_rejects_mismatch_without_publishing(repository, tmp_path, monkeypatch, mismatch):
    digest, versions, _ = repository
    raw = versions[digest]
    if mismatch == 'digest':
        del versions[digest]
        digest = 'c' * 64
        raw['file']['sha256'] = digest
        versions[digest] = raw

    if mismatch == 'size':
        raw['file']['size'] += 1
    if mismatch == 'package':
        monkeypatch.setattr(apk_catalog, '_badging', lambda path: "package: name='org.wrong.package' versionCode='12'\n")
    if mismatch == 'version':
        monkeypatch.setattr(apk_catalog, '_badging', lambda path: f"package: name='{PACKAGE}' versionCode='11'\n")
    with pytest.raises(HTTPException) as rejected:
        fdroid_catalog.import_application(*fdroid_catalog.find_release(PACKAGE, digest))
    assert rejected.value.status_code == 422
    assert not list(tmp_path.iterdir())


def test_control_route_authenticates_validates_and_publishes(repository, monkeypatch):
    digest, _, requests = repository
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setenv('EMULYTIX_CONTROL_TOKEN', 'fdroid-test-token')
    monkeypatch.setenv('EMULYTIX_DATABASE_URL', 'postgresql://unused')
    headers = {'Authorization': 'Bearer fdroid-test-token'}
    payload = {'package_name': PACKAGE, 'sha256': digest}
    stored = None

    def add(self, metadata, actor, *, reuse_exact):
        nonlocal stored
        assert reuse_exact
        stored = {'id': metadata['id']}
        return stored

    monkeypatch.setattr(EmulatorStore, 'matching_application', lambda self, package, sha, actor: stored)
    monkeypatch.setattr(EmulatorStore, 'add_application', add)
    assert required_permission('GET', ENDPOINT) == required_permission('POST', ENDPOINT) == 'devices.write'
    with TestClient(app) as client:
        assert client.get(ENDPOINT, params={'q': 'notes'}).status_code == 401
        assert client.post(ENDPOINT, headers=headers, json={**payload, 'url': 'https://somewhere.example/'}).status_code == 422
        assert not requests
        assert client.get(ENDPOINT, headers=headers, params={'q': 'notes'}).json()['items'][0]['package_name'] == PACKAGE
        result = client.post(ENDPOINT, headers=headers, json=payload)
        repeated = client.post(ENDPOINT, headers=headers, json=payload)
        unknown = client.post(ENDPOINT, headers=headers, json={**payload, 'sha256': '0' * 64})
    assert result.status_code == 201
    assert repeated.status_code == 200 and repeated.json() == result.json()
    assert unknown.status_code == 404
    assert sum(request.url.path == '/repo' + APK_PATH for request in requests) == 1


def test_concurrent_downloads_share_a_published_artifact(repository, control_client, database_dsn, tmp_path, monkeypatch):
    digest, _, _ = repository
    fdroid_catalog.search_applications(PACKAGE)
    download = fdroid_catalog.import_application
    ready = Barrier(2)

    def download_together(app, release):
        metadata = download(app, release)
        ready.wait(timeout=5)
        return metadata

    monkeypatch.setattr(fdroid_catalog, 'import_application', download_together)
    payload = {'package_name': PACKAGE, 'sha256': digest}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: control_client.post(ENDPOINT, json=payload), range(2)))
    assert sorted(result.status_code for result in results) == [200, 201]
    assert results[0].json() == results[1].json()
    with EmulatorStore(database_dsn).connect() as connection:
        rows = connection.execute('SELECT id FROM applications').fetchall()
    assert [str(row['id']) for row in rows] == [results[0].json()['id']]
    assert [file.name for file in tmp_path.glob('*.apk')] == [results[0].json()['id'] + '.apk']
