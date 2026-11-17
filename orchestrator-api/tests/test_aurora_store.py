import httpx
import pytest
from fastapi import HTTPException

from app import aurora_store


def release_index(*files):
    return {'isDirectory': True, 'contents': [
        {'path': '/downloads/AuroraStore', 'isDirectory': True, 'contents': [
            {'path': aurora_store.DIRECTORY, 'isDirectory': True, 'contents': list(files)},
        ]},
    ]}


def release_file(version, **overrides):
    name = f'AuroraStore-{version}.apk'
    return {'name': name, 'path': f'{aurora_store.DIRECTORY}/{name}', 'isDirectory': False,
            'mimeType': aurora_store.MIME_TYPE, 'size': 900, **overrides}


def mock_index(monkeypatch, response):
    def serve(request):
        assert request.url == aurora_store.INDEX_URL
        return response

    client = httpx.Client(transport=httpx.MockTransport(serve))
    monkeypatch.setattr(aurora_store.httpx, 'stream', lambda *args, **kwargs: client.stream(*args))


def test_aurora_selects_newest_vanilla_stable_semantic_version(monkeypatch):
    index = release_index(
        release_file('4.8.4'),
        release_file('4.10.0', size=1100),
        release_file('5.0.0-rc1'),
        release_file('6.0.0', path=f'{aurora_store.DIRECTORY}/Huawei/AuroraStore-6.0.0.apk'),
        release_file('7.0.0', size=True),
    )
    mock_index(monkeypatch, httpx.Response(200, json=index))
    assert aurora_store.find_latest_release() == aurora_store.Release('4.10.0', 1100)


@pytest.mark.parametrize('response', [
    httpx.Response(302, headers={'Location': 'https://example.org'}),
    httpx.Response(200, headers={'Content-Encoding': 'gzip'}, stream=httpx.ByteStream(b'bad gzip')),
    httpx.Response(200, content=b'not JSON'),
    httpx.Response(200, json=release_index(release_file('5.0.0-rc1'))),
    httpx.Response(200, content=b' ' * (aurora_store.MAX_INDEX_BYTES + 1)),
])
def test_aurora_unavailable_index(monkeypatch, response):
    mock_index(monkeypatch, response)
    with pytest.raises(aurora_store.AuroraUnavailable):
        aurora_store.find_latest_release()


def test_aurora_rejects_oversized_latest_stable(monkeypatch):
    index = release_index(release_file('4.8.3'), release_file('4.8.4', size=aurora_store.MAX_APK_BYTES + 1))
    mock_index(monkeypatch, httpx.Response(200, json=index))
    with pytest.raises(aurora_store.AuroraIncompatible):
        aurora_store.find_latest_release()


def test_aurora_passes_fixed_origin_package_version_size_and_signer_to_ingestion(monkeypatch):
    def verify(url, label, expected):
        assert url == 'https://auroraoss.com/downloads/AuroraStore/Release/AuroraStore-4.8.4.apk'
        assert label == 'Aurora Store (4.8.4)'
        assert expected.package_name == 'com.aurora.store'
        assert expected.version_name == '4.8.4'
        assert expected.version_code is None
        assert expected.size_bytes == 9362660
        assert expected.sha256 is None
        assert expected.signer_sha1 == '944275d7598bc03e488506064225a71990a22202'
        assert expected.signer_sha256 == '4c626157ad02bda3401a7263555f68a79663fc3e13a4d4369a12570941aa280f'
        return {'package_name': expected.package_name}

    monkeypatch.setattr(aurora_store, 'download_store_apk', verify)
    assert aurora_store.download_release(aurora_store.Release('4.8.4', 9362660)) == {'package_name': 'com.aurora.store'}


@pytest.mark.parametrize(('status', 'error'), [
    (413, aurora_store.AuroraIncompatible),
    (422, aurora_store.AuroraIncompatible),
    (502, aurora_store.AuroraUnavailable),
])
def test_aurora_classifies_download_verification_failure(monkeypatch, status, error):
    def fail(*args):
        raise HTTPException(status)

    monkeypatch.setattr(aurora_store, 'download_store_apk', fail)
    with pytest.raises(error):
        aurora_store.download_release(aurora_store.Release('4.8.4', 9362660))
