"""The published console fails closed unless development explicitly disables auth."""
import pytest
from cryptography.fernet import Fernet


@pytest.mark.parametrize('flag', [None, '', 'typo', '0'])
def test_missing_or_invalid_auth_setting_never_opens_console(client, database_dsn, monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv('EMULYTIX_AUTH_ENABLED', raising=False)
    else:
        monkeypatch.setenv('EMULYTIX_AUTH_ENABLED', flag)
    monkeypatch.setenv('EMULYTIX_DATABASE_URL', database_dsn)
    monkeypatch.setenv('EMULYTIX_AUTH_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('EMULYTIX_PUBLIC_ORIGIN', 'http://localhost:3100')
    monkeypatch.setenv('EMULYTIX_COOKIE_SECURE', 'false')
    assert client.get('/openapi.json').status_code == 401
    assert client.get('/console/summary').status_code == 401


def test_removed_legacy_routes_cannot_be_enabled_in_a_development_process(client, monkeypatch):
    monkeypatch.setenv('EMULYTIX_AUTH_ENABLED', 'false')
    monkeypatch.setenv('EMULYTIX_LEGACY_CONTROL_ENABLED', 'true')
    for method, path in [('POST', '/sessions'), ('GET', '/sessions'), ('GET', '/android/status'),
                         ('GET', '/ai/models'), ('GET', '/runtime-capabilities'),
                         ('POST', '/sessions/example/device/text')]:
        assert client.request(method, path, json={} if method == 'POST' else None).status_code == 404
    assert client.get('/health').json() == {'status': 'ok'}
