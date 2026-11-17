import json

from fastapi import HTTPException
import httpx
import pytest

from app import ai_provider_settings, journey_provider
from app.ai_provider_probe import probe_shared_model
from conftest import CONTROL_TOKEN
from test_authentication import auth_store
from test_user_roles import signed_in


@pytest.mark.parametrize('provider,model,path,body', [
    ('ollama', 'gemma4', '/api/tags', {'models': [{'name': 'gemma4:latest'}]}),
    ('ollama', 'gemma4:latest', '/api/tags', {'models': [{'model': 'gemma4'}]}),
    ('deepseek', 'deepseek-flash', '/models', {'data': [{'id': 'deepseek-flash'}]}),
])
def test_shared_probe_checks_the_configured_model(monkeypatch, provider, model, path, body):
    local = provider == 'ollama'
    url = httpx.URL('http://ollama:11434/api/chat') if local else 'https://api.deepseek.com/chat/completions'
    headers = {} if local else {'Authorization': 'Bearer fixture-secret'}

    def respond(request):
        assert request.method == 'GET' and request.url.path == path and not request.url.query
        assert request.url.host == ('ollama' if local else 'api.deepseek.com')
        assert request.headers.get('authorization') == (None if local else 'Bearer fixture-secret')
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        def stream(*args, trust_env, follow_redirects, **kwargs):
            assert not trust_env and not follow_redirects
            return client.stream(*args, **kwargs)

        monkeypatch.setattr(httpx, 'stream', stream)
        probe_shared_model(provider, {'model': model, 'headers': headers, 'url': url})


@pytest.mark.parametrize('status,body,expected', [
    (401, b'secret from upstream', (422, 'provider_auth_failed')),
    (403, b'secret from upstream', (422, 'provider_auth_failed')),
    (429, b'secret from upstream', (429, 'provider_busy')),
    (302, b'secret from upstream', (503, 'provider_unavailable')),
    (200, b'{"data":[]}', (422, 'provider_model_unavailable')),
    (200, b'secret from upstream', (503, 'provider_unavailable')),
])
def test_probe_errors_only_return_safe_codes(monkeypatch, status, body, expected):
    with httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(status, stream=httpx.ByteStream(body)),
    )) as client:
        monkeypatch.setattr(httpx, 'stream', lambda *args, **kwargs: client.stream(*args, headers=kwargs['headers']))
        with pytest.raises(HTTPException) as error:
            probe_shared_model('deepseek', {'model': 'deepseek-flash', 'headers': {},
                                           'url': 'https://api.deepseek.com/chat/completions'})
    assert (error.value.status_code, error.value.detail) == (expected[0], {'code': expected[1]})


def test_probe_routes_respect_provider_ownership_and_use_the_saved_configuration(auth_store, app_module, monkeypatch):
    _, admin, _ = signed_in(auth_store, app_module, 'admin', 'probe-admin')
    viewer, viewer_client, _ = signed_in(auth_store, app_module, 'viewer', 'probe-viewer')
    settings_path = '/console/account/ai-providers'
    test_path = settings_path + '/test'
    requests = []
    monkeypatch.setenv('EMULYTIX_DEEPSEEK_API_KEY', 'fallback-key')
    monkeypatch.setattr(journey_provider.ChatGPTManager, 'available', property(lambda _: True))

    def shared_probe(provider, settings):
        requests.append((provider, settings))

    monkeypatch.setattr(ai_provider_settings, 'probe_shared_model', shared_probe)
    assert viewer_client.post(test_path, json={'provider': 'deepseek'}).status_code == 403
    assert viewer_client.post(test_path, json={'provider': 'ollama'}).status_code == 403
    assert not requests
    assert admin.patch(settings_path, json={'deepseek_key': 'private-key', 'deepseek_model': 'deepseek-flash'}).status_code == 200
    result = admin.post(test_path, json={'provider': 'deepseek'})
    assert result.json() == {'provider': 'deepseek', 'status': 'ok'} and 'private-key' not in result.text
    assert requests == [('deepseek', {'model': 'deepseek-flash', 'url': 'https://api.deepseek.com/chat/completions',
                                     'headers': {'Authorization': 'Bearer private-key'}})]

    missing = viewer_client.post(test_path, json={'provider': 'openai'})
    assert missing.status_code == 409 and missing.json() == {'detail': {'code': 'chatgpt_required'}}
    saved_auth = {'auth_mode': 'chatgpt', 'tokens': {'access_token': 'private-openai-access', 'refresh_token': 'refresh'}}
    payload = {'provider': 'chatgpt', 'user_id': str(viewer['id']), 'auth': saved_auth}
    encrypted = auth_store.config.cipher.encrypt(json.dumps(payload).encode()).decode()
    with auth_store.connect() as connection:
        connection.execute('INSERT INTO chatgpt_connections(user_id, credentials_ciphertext) VALUES(%s,%s)',
                           (viewer['id'], encrypted))

    def planner(credentials, instructions, *, timeout):
        assert credentials == saved_auth and timeout == 20
        assert instructions == 'Connectivity check: return supported=false and no steps.'
        return {'supported': False}, credentials

    monkeypatch.setattr(journey_provider, 'run_planner', planner)
    result = viewer_client.post(test_path, json={'provider': 'openai'})
    assert result.json() == {'provider': 'openai', 'status': 'ok'} and 'private-openai-access' not in result.text
    assert viewer_client.post('/console/recipes/generate', json={'instructions': 'A valid free goal.'}).status_code == 403
    viewer_client.cookies.clear()
    viewer_client.headers['Authorization'] = f'Bearer {CONTROL_TOKEN}'
    assert viewer_client.post(test_path, json={'provider': 'openai'}).status_code == 401
