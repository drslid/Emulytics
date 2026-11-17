import httpx
import pytest
from fastapi import HTTPException

from app import apkmirror_catalog as mirror
from app.access import required_permission


def row(title, path, date=''):
    return f'''<div class="appRow"><div class="table-cell">
            <h5 title="{title}" class="appRowTitle wrapText"><a href="{path}">{title}</a></h5>
            <span class="dateyear_utc" data-utcdate="{date}">August 5, 2026</span></div></div>'''


@pytest.fixture
def upstream(monkeypatch):
    monkeypatch.setattr(mirror, '_CACHE', mirror.OrderedDict())
    monkeypatch.setattr(mirror, '_NEXT_REQUEST', 0.0)
    monkeypatch.setattr(mirror.time, 'sleep', lambda _: None)

    def mock(handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))

        def stream(method, url, **kwargs):
            assert kwargs['follow_redirects'] is False
            assert kwargs['trust_env'] is False
            return client.stream(method, url, headers=kwargs['headers'])

        monkeypatch.setattr(httpx, 'stream', stream)
        return client

    return mock


def test_search_and_version_metadata_use_only_canonical_public_links(upstream):
    apk = '/apk/linkedin/linkedin-linkedin/'
    release = apk + 'linkedin-4-1-1230-release/'
    variant = release + 'linkedin-4-1-1230-2-android-apk-download/'
    calls = []

    def respond(request):
        calls.append(request.url)
        assert request.url.host == 'www.apkmirror.com'
        if request.url.path == '/':
            assert request.url.params['s'] == 'LinkedIn & Jobs'
            assert request.url.params['searchtype'] == 'app'
            markup = row('LinkedIn &amp; Jobs', apk) + row('Duplicate', mirror.ORIGIN + apk)
            markup += row('External', 'https://elsewhere.test' + apk) + row('Unexpected', release)
        else:
            assert request.url.path == apk
            markup = '<h1 class="app-title" title="LinkedIn &amp; Jobs">LinkedIn &amp; Jobs</h1>'
            markup += row('LinkedIn &amp; Jobs 4.1.1230 (nodpi)', variant, '08/5/2026 05:37 UTC')
            markup += row('LinkedIn &amp; Jobs 4.1.1229', apk + 'linkedin-4-1-1229-release/', 'invalid')
            markup += row('Snapchat', '/apk/snap-inc/snapchat/snapchat-1-release/', '08/5/2026 02:00 UTC')
            markup += row('Nonce', variant + '?key=123', '08/5/2026 05:37 UTC')
        return httpx.Response(200, headers={'Content-Type': 'text/html; charset=utf-8'},
                              stream=httpx.ByteStream(markup.encode()))

    with upstream(respond):
        results = mirror.search_applications('  LinkedIn   & Jobs  ')
        assert results['items'] == [{'id': 'linkedin/linkedin-linkedin', 'name': 'LinkedIn & Jobs',
                                     'source_url': mirror.ORIGIN + apk, 'versions': []}]
        assert mirror.search_applications('LinkedIn & Jobs') == results
        versions = mirror.list_versions('linkedin/linkedin-linkedin')['versions']
        assert versions[0] == {'id': 'linkedin-4-1-1230-release/linkedin-4-1-1230-2-android-apk-download',
                               'version_name': '4.1.1230 (nodpi)', 'added_at': '2026-08-05T05:37:00+00:00',
                               'source_url': mirror.ORIGIN + variant}
        assert len(versions) == 2 and versions[1]['added_at'] is None
        with pytest.raises(HTTPException) as error:
            mirror.list_versions('linkedin/../../download.php')
        assert error.value.status_code == 422
    assert len(calls) == 2


@pytest.mark.parametrize('status', [302, 403, 429])
def test_upstream_restrictions_are_not_bypassed(upstream, status):
    def respond(request):
        assert request.url.host == 'www.apkmirror.com'
        return httpx.Response(status, headers={'Location': 'https://elsewhere.test/download.php'}, text='private upstream error')

    with upstream(respond):
        with pytest.raises(HTTPException) as error:
            mirror.search_applications('LinkedIn')
    assert error.value.status_code == 503
    assert 'private upstream error' not in error.value.detail


def test_search_can_reach_apps_after_the_first_public_page(upstream):
    next_link = '<a class="nextpostslink" rel="next" href="https://untrusted.test">Next page</a>'

    def respond(request):
        assert request.url.host == 'www.apkmirror.com'
        assert request.url.params['s'] == 'LinkedIn'
        if 'page' in request.url.params:
            assert request.url.params['page'] == '2'
            html = row('LinkedIn: Community &amp; Network', '/apk/linkedin/linkedin-linkedin/')
        else:
            html = row('LinkedIn Connected', '/apk/linkedin/connected/')
        return httpx.Response(200, headers={'Content-Type': 'text/html'},
                              stream=httpx.ByteStream((html + next_link).encode()))

    with upstream(respond):
        assert [item['id'] for item in mirror.search_applications('LinkedIn')['items']] == [
            'linkedin/connected', 'linkedin/linkedin-linkedin',
        ]


def test_route_permissions_only_enable_catalogue_reads():
    for path in ('/console/applications/apkmirror', '/console/applications/apkmirror/versions'):
        assert required_permission('GET', path) == 'devices.write'
        assert required_permission('POST', path) is None
