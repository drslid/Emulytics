import json
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException, Request

from app import auth, journey_provider
from app.automation_models import GoalInput
from app.automation_routes import generate_recipe, recipe_providers


@pytest.mark.parametrize('provider', ['ollama', 'deepseek'])
def test_external_planner_sends_only_the_goal_and_gets_structured_result(monkeypatch, provider):
    monkeypatch.setenv('EMULYTIX_OLLAMA_URL', 'http://host.docker.internal:11434/')
    monkeypatch.setenv('EMULYTIX_OLLAMA_MODEL', 'qwen3:8b')
    monkeypatch.setenv('EMULYTIX_DEEPSEEK_API_KEY', 'fixture-secret')
    monkeypatch.delenv('EMULYTIX_DEEPSEEK_MODEL', raising=False)
    goal = 'Ouvre la calculatrice installée et capture son écran.'
    result = {'supported': True, 'reason': 'Calculatrice ouverte', 'name': 'Calculatrice', 'steps_json': '[]'}

    def response(payload):
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(payload).encode()))

    def respond(request):
        data = json.loads(request.content)
        assert request.method == 'POST'
        assert data['stream'] is False and 'tools' not in data
        assert data['messages'][1] == {'role': 'user', 'content': json.dumps(goal, ensure_ascii=False)}
        content = {'content': json.dumps(result)}
        if provider == 'ollama':
            assert str(request.url) == 'http://host.docker.internal:11434/api/chat'
            assert 'authorization' not in request.headers
            assert data['model'] == 'qwen3:8b' and data['format'] == journey_provider.SCHEMA
            return response({'message': content})
        assert str(request.url) == 'https://api.deepseek.com/chat/completions'
        assert request.headers['Authorization'] == 'Bearer fixture-secret'
        assert data['model'] == 'deepseek-flash' and data['response_format'] == {'type': 'json_object'}
        return response({'choices': [{'message': content}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        def stream(method, url, *, trust_env, follow_redirects, **kwargs):
            assert trust_env is False and follow_redirects is False
            return client.stream(method, url, **kwargs)

        monkeypatch.setattr(httpx, 'stream', stream)
        settings = journey_provider.external_planner_settings(provider)
        assert journey_provider.run_external_planner(provider, goal, settings) == result


def test_local_only_ollama_and_public_provider_status(monkeypatch):
    monkeypatch.setenv('EMULYTIX_DEEPSEEK_API_KEY', 'fixture-secret')
    monkeypatch.setenv('EMULYTIX_DEEPSEEK_MODEL', 'deepseek-flash')
    monkeypatch.setenv('EMULYTIX_OLLAMA_MODEL', 'qwen3:8b')
    for url in ('https://ollama.com', 'http://user@localhost:11434', 'http://localhost/another-path'):
        monkeypatch.setenv('EMULYTIX_OLLAMA_URL', url)
        assert journey_provider.external_planner_settings('ollama') is None
    monkeypatch.setenv('EMULYTIX_OLLAMA_URL', 'http://127.0.0.1:11434')
    monkeypatch.setenv('EMULYTIX_OLLAMA_MODEL', 'qwen3:cloud')
    state = {'auth_user': {'id': uuid4()}}
    assert recipe_providers(Request({'type': 'http', 'state': state})) == {'ollama': None, 'deepseek': 'deepseek-flash'}
    with pytest.raises(HTTPException) as error:
        recipe_providers(Request({'type': 'http'}))
    assert error.value.status_code == 401


def test_builtin_goal_does_not_contact_selected_provider(monkeypatch):
    monkeypatch.setattr(auth, 'auth_enabled', lambda: pytest.fail('Built-in goals must work without an account'))
    payload = GoalInput(instructions='Ouvre les paramètres du téléphone et donne-moi la version d’Android.', provider='deepseek')
    assert generate_recipe(payload, Request({'type': 'http'}), None)['source'] == 'verified_template'


@pytest.mark.parametrize('selected, action, expected_source', [
    ('ollama', 'screenshot', 'ollama'),
    ('deepseek', 'screenshot', 'deepseek'),
    (None, 'screenshot', 'chatgpt'),
    ('ollama', 'install_apk', None),
])
def test_selected_provider_reuses_journey_validation(monkeypatch, selected, action, expected_source):
    monkeypatch.setattr(auth, 'auth_enabled', lambda: True)
    monkeypatch.setattr(auth.AuthConfig, 'load', lambda: object())
    actor_id = uuid4()
    goal = 'Ouvre la calculatrice installée et capture son écran.'

    class Provider:
        def __init__(self, _config):
            pass

        def current_user(self, session):
            assert session == 'fixture-session'
            return {'id': actor_id}

        def limit(self, *args, **kwargs):
            assert args[:2] == ('journey-generation', str(actor_id))

        def generate(self, session, instructions, provider):
            assert (session, instructions, provider) == ('fixture-session', goal, selected or 'openai')
            assertion = {'type': 'package', 'value': 'com.example.calculator'}
            return {'name': 'Calculatrice', 'reason': 'Calculatrice ouverte', 'supported': True, 'steps_json': json.dumps([
                {'id': 'open', 'action': 'open_app', 'args': {'package_name': 'com.example.calculator'}, 'assert': assertion},
                {'id': 'verify', 'action': action, 'args': {}, 'assert': assertion},
            ])}

    monkeypatch.setattr(journey_provider, 'JourneyProvider', Provider)
    request = Request({'type': 'http', 'headers': [(b'cookie', b'emulytix_session=fixture-session')]})
    payload = GoalInput(instructions=goal, **({'provider': selected} if selected else {}))
    if expected_source is None:
        with pytest.raises(HTTPException) as error:
            generate_recipe(payload, request, None)
        assert error.value.status_code == 422
    else:
        result = generate_recipe(payload, request, None)
        assert result['source'] == expected_source and result['requires_test'] is True
