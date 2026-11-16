from copy import deepcopy

from fastapi import HTTPException
import httpx
import pytest

from app import aptoide_catalog as catalog


LINKEDIN = 'com.linkedin.android'
SNAPCHAT = 'com.snapchat.android'
LINKEDIN_ID = 70242382
LINKEDIN_MD5 = '76cafa62a48277cd6873bf3347b66fed'
LINKEDIN_VERSION = f'{LINKEDIN_ID}:{LINKEDIN_MD5}'


def metadata(package=LINKEDIN, app_id=LINKEDIN_ID, md5=LINKEDIN_MD5):
    return {'id': app_id, 'package': package, 'name': 'LinkedIn', 'obb': None,
            'aab': {'required_split_types': [], 'splits': []}, 'file': {
                'vername': '4.1.821', 'vercode': 172900, 'md5sum': md5, 'filesize': 78514532,
                'added': '2025-03-23 06:00:48',
                'path': f'https://pool.apk.aptoide.com/sincmaster66666/com-linkedin-android-172900-{app_id}-{md5}.apk',
                'hardware': {'sdk': 26, 'cpus': ['armeabi-v7a', 'x86-64']}, 'malware': {'rank': 'TRUSTED'},
                'signature': {'sha1': '44:3C:B9:97:71:8D:0A:C5:16:28:88:BA:E5:E4:72:45:82:86:26:76'},
            }}


def response(**data):
    return httpx.Response(200, json={'info': {'status': 'OK'}, **data})


def stub_client(monkeypatch, handler):
    monkeypatch.setattr(catalog, '_client', lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False))


def test_search_includes_store_titles_before_loading_compatible_versions(monkeypatch):
    def handler(request):
        assert request.url.host == 'ws75.aptoide.com'
        assert request.url.path == '/api/7/apps/search'
        assert request.url.params['query'] == 'LinkedIn & Snapchat'
        assert request.url.params['limit'] == str(catalog.SEARCH_LIMIT)
        return response(datalist={'list': [{'package': LINKEDIN, 'name': 'LinkedIn'}, {'package': SNAPCHAT, 'name': 'Snapchat'},
                                           {'package': LINKEDIN, 'name': 'Duplicate'}, {'package': 'bad package', 'name': 'Invalid'}]})

    stub_client(monkeypatch, handler)
    assert catalog.search_applications(' LinkedIn & Snapchat ') == {'items': [
        {'package_name': LINKEDIN, 'name': 'LinkedIn', 'versions': []}, {'package_name': SNAPCHAT, 'name': 'Snapchat', 'versions': []},
    ]}


def test_versions_check_exact_compatibility_and_keep_the_selected_release(monkeypatch):
    compatible = metadata()
    split = deepcopy(compatible)
    split['id'] += 1
    split['aab']['required_split_types'] = ['ABI']
    arm_only = deepcopy(compatible)
    arm_only['id'] += 2
    arm_only['file']['hardware']['cpus'] = ['arm64-v8a']
    ids = []

    def handler(request):
        if request.url.path == '/api/7/listAppVersions':
            assert request.url.params['package_name'] == LINKEDIN
            assert request.url.params['aab'] == '0'
            return response(list=[compatible, split, arm_only])
        assert request.url.path == '/api/7/app/get'
        assert request.url.params['nodes'] == 'meta' and request.url.params['aab'] == '1'
        app_id = int(request.url.params['app_id'])
        ids.append(app_id)
        item = {compatible['id']: compatible, split['id']: split}[app_id]
        return response(nodes={'meta': {'data': item}})

    stub_client(monkeypatch, handler)
    assert catalog.list_versions(LINKEDIN) == {'versions': [{
        'id': LINKEDIN_VERSION, 'version_name': '4.1.821', 'version_code': 172900,
        'added_at': '2025-03-23T06:00:48Z', 'size_bytes': 78514532,
    }]}
    release = catalog.find_release(LINKEDIN, LINKEDIN_VERSION)
    assert ids == [LINKEDIN_ID, LINKEDIN_ID + 1, LINKEDIN_ID]
    assert release.signer_sha256 == catalog.PUBLISHER_CERTIFICATES[LINKEDIN][1]
    assert release.url.startswith('https://pool.apk.aptoide.com/')


@pytest.mark.parametrize('field,value', [
    ('aab', {'required_split_types': [], 'splits': [{'type': 'density'}]}),
    ('obb', {'main': {}}),
    ('file.hardware', {'sdk': 30, 'cpus': ['x86_64']}),
    ('file.filesize', catalog.MAX_APK_BYTES + 1),
    ('file.malware', {'rank': 'WARNING'}),
    ('file.md5sum', '0' * 32),
    ('file.signature', {'sha1': '0' * 40}),
    ('file.path', 'https://pool.apk.aptoide.com.evil.example/mirror.apk'),
    ('file.path', 'https://pool.apk.aptoide.com@evil.example/mirror.apk'),
    ('file.added', 'not a date'),
])
def test_exact_lookup_rejects_unsafe_or_changed_metadata(monkeypatch, field, value):
    item = metadata()
    target, key = (item['file'], field.removeprefix('file.')) if field.startswith('file.') else (item, field)
    target[key] = value
    stub_client(monkeypatch, lambda request: response(nodes={'meta': {'data': item}}))
    with pytest.raises(HTTPException) as failure:
        catalog.find_release(LINKEDIN, LINKEDIN_VERSION)
    assert failure.value.status_code == 404


def test_other_publishers_need_google_play_validation(monkeypatch):
    package = 'org.example.app'
    item = metadata(package)
    stub_client(monkeypatch, lambda request: response(nodes={'meta': {'data': item}}))
    with pytest.raises(HTTPException) as failure:
        catalog.find_release(package, LINKEDIN_VERSION)
    assert failure.value.status_code == 404
    item['file']['malware']['reason'] = {'thirdparty_validated': {'store': 'Google Play'}}
    assert catalog.find_release(package, LINKEDIN_VERSION).signer_sha256 is None


def test_snapchat_web_variant_keeps_exact_version(monkeypatch):
    app_id, md5 = catalog.SNAPCHAT_WEB_VERSION_ID.split(':')
    item = metadata(SNAPCHAT, int(app_id), md5)
    item['file'].update(vername='500003.0.1', signature={'sha1': catalog.PUBLISHER_CERTIFICATES[SNAPCHAT][0]})
    stub_client(monkeypatch, lambda request: response(nodes={'meta': {'data': item}}))
    result = catalog.find_release(SNAPCHAT, catalog.SNAPCHAT_WEB_VERSION_ID).view()
    assert result['variant'] == 'web'
    assert result['id'] == catalog.SNAPCHAT_WEB_VERSION_ID and result['version_name'] == '500003.0.1'


def test_version_details_are_bounded_and_a_missing_version_does_not_fail_the_list(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == '/api/7/listAppVersions':
            return response(list=[metadata(app_id=index + 1) for index in range(catalog.VERSION_LIMIT + 5)])
        return httpx.Response(404)

    stub_client(monkeypatch, handler)
    assert catalog.list_versions(LINKEDIN) == {'versions': []}
    assert len(calls) == catalog.DETAIL_LIMIT + 1


@pytest.mark.parametrize('upstream', [httpx.Response(302, headers={'Location': 'https://evil.example/catalog'}),
                                      httpx.Response(200, content=b'x' * (catalog.MAX_RESPONSE_BYTES + 1))])
def test_catalog_rejects_redirect_and_oversized_responses(monkeypatch, upstream):
    calls = []

    def handler(request):
        calls.append(request)
        return upstream

    stub_client(monkeypatch, handler)
    with pytest.raises(HTTPException) as failure:
        catalog.search_applications('Snapchat')
    assert failure.value.status_code == 503 and len(calls) == 1
