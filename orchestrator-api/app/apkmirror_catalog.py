"""Search APKMirror's public catalogue and link to its browser download flow."""

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import re
import threading
import time
from urllib.parse import urlencode

from fastapi import HTTPException
import httpx


ORIGIN = 'https://www.apkmirror.com'
_HEADERS = {'User-Agent': 'Emulytics (+https://github.com/drslid/Emulytics)',
            'Accept': 'text/html', 'Accept-Encoding': 'identity'}
_SLUG = r'[a-z0-9][a-z0-9_-]{0,119}'
APP_ID = f'{_SLUG}/{_SLUG}'
_RELEASE = r'[a-z0-9][a-z0-9_-]{0,159}-release'
_VARIANT = r'[a-z0-9][a-z0-9_-]{0,159}-android-apk-download'
_PAGE_PATH = re.compile(rf'(?:{re.escape(ORIGIN)})?(/apk/({APP_ID})(?:/({_RELEASE})(?:/{_VARIANT})?)?)/?')
_FETCH_LOCK = threading.Lock()
_CACHE = OrderedDict()
_NEXT_REQUEST = 0.0
_PAGE_LIMIT = 1024 * 1024
_RESULT_LIMIT = 12
_APPLICATION_LIMIT = 20


@dataclass
class _Row:
    name: str
    path: str
    app_id: str
    release: str | None
    added_at: str | None = None


class _CataloguePage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.name = None
        self.rows: list[_Row] = []
        self.has_next_page = False
        self._heading = None
        self._row = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        classes = (attrs.get('class') or '').split()
        if tag == 'h1' and 'app-title' in classes:
            self.name = _title(attrs)
        if tag == 'div' and 'appRow' in classes:
            self._row = None
        if tag == 'h5' and 'appRowTitle' in classes:
            self._heading = _title(attrs)
        if tag == 'a' and 'nextpostslink' in classes and attrs.get('rel') == 'next':
            self.has_next_page = True
        if tag == 'a' and self._heading and len(self.rows) < 100:
            match = _PAGE_PATH.fullmatch(attrs.get('href') or '')
            if match:
                path, app_id, release = match.groups()
                self._row = _Row(self._heading, path + '/', app_id, release)
                self.rows.append(self._row)
                self._heading = None
        if tag == 'span' and self._row and not self._row.added_at and 'data-utcdate' in attrs:
            self._row.added_at = _utc_date(attrs['data-utcdate'])

    def handle_endtag(self, tag):
        if tag == 'h5':
            self._heading = None


def _title(attributes):
    return ' '.join((attributes.get('title') or '').split())[:200]


def _utc_date(value):
    try:
        return datetime.strptime(value or '', '%m/%d/%Y %H:%M UTC').replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def _fetch(url):
    global _NEXT_REQUEST
    if not _FETCH_LOCK.acquire(timeout=4):
        raise HTTPException(503, 'APKMirror est temporairement indisponible.')
    try:
        cached = _CACHE.get(url)
        if cached and cached[0] > time.monotonic():
            _CACHE.move_to_end(url)
            return cached[1]
        time.sleep(max(0, _NEXT_REQUEST - time.monotonic()))
        _NEXT_REQUEST = time.monotonic() + 3  # APKMirror robots.txt crawl delay for generic clients.
        deadline = time.monotonic() + 8
        content = bytearray()
        with httpx.stream('GET', url, headers=_HEADERS, timeout=4, follow_redirects=False, trust_env=False) as response:
            response.raise_for_status()
            if response.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'text/html':
                raise ValueError('Invalid catalogue media type')
            for chunk in response.iter_raw():
                if len(content) + len(chunk) > _PAGE_LIMIT or time.monotonic() > deadline:
                    raise ValueError('Catalogue limit exceeded')
                content.extend(chunk)
        page = _CataloguePage()
        page.feed(content.decode('utf-8', errors='replace'))
        page.close()
        _CACHE[url] = time.monotonic() + 300, page
        _CACHE.move_to_end(url)
        if len(_CACHE) > 24:
            _CACHE.popitem(last=False)
        return page
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            raise HTTPException(404, 'Page APKMirror introuvable.') from None
        raise HTTPException(503, 'APKMirror est temporairement indisponible.') from None
    except (httpx.RequestError, ValueError):
        raise HTTPException(503, 'APKMirror est temporairement indisponible.') from None
    finally:
        _FETCH_LOCK.release()


def search_applications(query):
    query = ' '.join(query.split())
    if len(query) < 2:
        raise HTTPException(422, 'Saisissez au moins deux caractères.')
    params = urlencode({'post_type': 'app_release', 'searchtype': 'app', 's': query})
    source_url = f'{ORIGIN}/?{params}'
    pages = [_fetch(source_url)]
    if pages[0].has_next_page:
        try:
            pages.append(_fetch(source_url + '&page=2'))
        except HTTPException:
            pass  # A failed next page does not hide the first page's results.
    items = {}
    for page in pages:
        for row in page.rows:
            if row.release is None and row.app_id not in items:
                items[row.app_id] = {'id': row.app_id, 'name': row.name, 'versions': [], 'source_url': ORIGIN + row.path}
    return {'items': list(items.values())[:_APPLICATION_LIMIT], 'source_url': source_url}


def list_versions(app_id):
    if not re.fullmatch(APP_ID, app_id):
        raise HTTPException(422, 'Identifiant APKMirror invalide.')
    page = _fetch(f'{ORIGIN}/apk/{app_id}/')
    versions = {}
    for row in page.rows:
        if row.app_id != app_id or not row.release or row.path in versions:
            continue
        title = row.name.removeprefix(f'{page.name} ').strip() or row.name
        versions[row.path] = {'id': row.path.removeprefix(f'/apk/{app_id}/').rstrip('/'),
                              'version_name': title, 'added_at': row.added_at, 'source_url': ORIGIN + row.path}
        if len(versions) == _RESULT_LIMIT:
            break
    return {'versions': list(versions.values())}
