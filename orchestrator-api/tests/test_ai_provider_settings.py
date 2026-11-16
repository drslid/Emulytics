import json

from cryptography.fernet import Fernet, InvalidToken
import pytest
from pydantic import ValidationError

from app import journey_provider
from app.ai_provider_settings import AiProviderPatch, _encrypt_deepseek_key, external_planner_settings
from conftest import CONTROL_TOKEN
from test_authentication import auth_store
from test_user_roles import signed_in


@pytest.mark.parametrize('url', [
    'https://ollama.com',
    'http://user:password@localhost:11434',
    'http://localhost/another-path',
    'http://localhost/?',
    'http://localhost/#',
    'http://localhost:0',
    'http://127.0.0.1%0a:11434',
    'http://192.168.1.5\\@localhost:11434',
    'http://169.254.169.254',
    'http://[::ffff:8.8.8.8]',
    'http://[fe80::1]',
])
def test_ollama_rejects_non_local_or_ambiguous_targets(url):
    with pytest.raises(ValidationError):
        AiProviderPatch(ollama_url=url)
    assert external_planner_settings('ollama', {'ollama_url': url, 'ollama_model': 'qwen3:8b'}) is None


@pytest.mark.parametrize('url', [
    'http://host.docker.internal:11434',
    'http://127.0.0.1:11434',
    'http://192.168.1.5:11434',
    'https://[fd00::1]:11434',
])
def test_ollama_uses_the_same_local_validation_for_settings_and_requests(url):
    payload = AiProviderPatch(ollama_url=url, ollama_model='qwen3:8b')
    settings = external_planner_settings('ollama', payload.model_dump())
    assert str(settings['url']) == f'{url}/api/chat'
    assert settings['headers'] == {}
    with pytest.raises(ValidationError):
        AiProviderPatch(ollama_model='qwen3:cloud')


def test_deepseek_uses_the_saved_installation_settings_before_environment(monkeypatch):
    monkeypatch.setenv('EMULYTIX_DEEPSEEK_API_KEY', 'environment-key')
    monkeypatch.setenv('EMULYTIX_DEEPSEEK_MODEL', 'environment-model')
    cipher = Fernet(Fernet.generate_key())
    key = AiProviderPatch(deepseek_key=' saved-key ').deepseek_key
    assert 'saved-key' not in repr(key)
    encrypted = _encrypt_deepseek_key(cipher, key.get_secret_value())
    assert 'saved-key' not in encrypted
    row = {'deepseek_key_ciphertext': encrypted, 'deepseek_model': 'saved-model'}
    assert external_planner_settings('deepseek', row, cipher=cipher) == {
        'model': 'saved-model', 'url': 'https://api.deepseek.com/chat/completions',
        'headers': {'Authorization': 'Bearer saved-key'},
    }
    with pytest.raises(InvalidToken):
        external_planner_settings('deepseek', row, cipher=Fernet(Fernet.generate_key()))
    assert external_planner_settings('deepseek') == {
        'model': 'environment-model', 'url': 'https://api.deepseek.com/chat/completions',
        'headers': {'Authorization': 'Bearer environment-key'},
    }


def test_shared_settings_require_admin_and_keep_the_key_private(auth_store, app_module, monkeypatch):
    for suffix in ('API_KEY', 'MODEL'):
        monkeypatch.delenv(f'EMULYTIX_DEEPSEEK_{suffix}', raising=False)
    _, admin_client, _ = signed_in(auth_store, app_module, 'admin', 'provider-admin')
    _, other_client, _ = signed_in(auth_store, app_module, 'builder', 'provider-builder')
    path = '/console/account/ai-providers'
    assert admin_client.get(path).json()['can_edit'] is True
    assert other_client.get(path).json()['can_edit'] is False
    assert other_client.get(path).json()['active_provider'] == 'openai'
    assert other_client.patch(path, json={'ollama_url': 'http://ollama:11434'}).status_code == 403
    assert other_client.patch(path, json={'active_provider': 'deepseek'}).status_code == 403
    assert other_client.patch(path, json={'deepseek_key': 'unauthorized-key'}).status_code == 403
    assert other_client.patch(path, json={'deepseek_model': 'unauthorized-model'}).status_code == 403
    assert admin_client.patch(path, json={'active_provider': 'deepseek'}).status_code == 409
    assert other_client.get(path).json()['active_provider'] == 'openai'

    shared = admin_client.patch(path, json={'ollama_url': 'http://ollama:11434', 'ollama_model': 'qwen3:8b'})
    assert shared.status_code == 200 and shared.json()['ollama']['configured']
    secret = 'installation-deepseek-test-key'
    configured = admin_client.patch(path, json={'active_provider': 'deepseek', 'deepseek_key': secret})
    assert configured.status_code == 200 and secret not in configured.text
    assert configured.json()['deepseek'] == {'model': 'deepseek-flash', 'has_key': True, 'has_saved_key': True}
    assert admin_client.patch(path, json={'deepseek_model': 'deepseek-pro'}).json()['deepseek']['has_saved_key']
    shared_status = other_client.get(path)
    assert secret not in shared_status.text
    assert shared_status.json()['deepseek'] == {'model': 'deepseek-pro', 'has_key': True, 'has_saved_key': True}
    assert other_client.get('/console/recipes/providers').json() == {
        'active_provider': 'deepseek', 'ollama': 'qwen3:8b', 'deepseek': 'deepseek-pro',
    }
    with auth_store.connect() as connection:
        row = connection.execute('SELECT deepseek_key_ciphertext FROM ai_provider_settings WHERE singleton').fetchone()
        encrypted = row['deepseek_key_ciphertext']
        assert secret not in encrypted and encrypted not in shared_status.text
        assert json.loads(auth_store.config.cipher.decrypt(encrypted.encode()))['key'] == secret
        assert secret not in str(connection.execute('SELECT * FROM audit_log').fetchall())

    goal = 'Ouvre la calculatrice installée et capture son écran.'

    def external(provider, instructions, settings):
        assert (provider, instructions) == ('deepseek', goal)
        assert settings == {'model': 'deepseek-pro', 'url': 'https://api.deepseek.com/chat/completions',
                            'headers': {'Authorization': f'Bearer {secret}'}}
        return {'supported': False, 'reason': 'Unavailable app'}

    monkeypatch.setattr(journey_provider, 'run_external_planner', external)
    generated = other_client.post('/console/recipes/generate', json={'instructions': goal})
    assert generated.json() == {'detail': {'code': 'unsupported_goal'}}

    invalid = admin_client.patch(path, json={'deepseek_key': f'{secret}\ninvalid'})
    assert invalid.status_code == 422 and secret not in invalid.text
    cleared = admin_client.patch(path, json={'deepseek_key': None, 'deepseek_model': None}).json()
    assert cleared['deepseek']['has_key'] is False and cleared['active_provider'] == 'deepseek'
    generation = other_client.post('/console/recipes/generate', json={'instructions': goal})
    assert generation.status_code == 409 and generation.json() == {'detail': {'code': 'provider_unconfigured'}}
    assert admin_client.patch(path, json={'active_provider': 'ollama'}).json()['active_provider'] == 'ollama'
    assert admin_client.patch(path, json={'active_provider': 'openai'}).json()['active_provider'] == 'openai'
    monkeypatch.setattr(journey_provider.ChatGPTManager, 'available', property(lambda _: True))
    no_connection = other_client.post('/console/recipes/generate', json={'instructions': goal})
    assert no_connection.status_code == 409 and no_connection.json() == {'detail': {'code': 'chatgpt_required'}}
    monkeypatch.setenv('EMULYTIX_DEEPSEEK_API_KEY', 'environment-test-key')
    monkeypatch.setenv('EMULYTIX_DEEPSEEK_MODEL', 'environment-model')
    inherited = other_client.get(path).json()['deepseek']
    assert inherited == {'model': 'environment-model', 'has_key': True, 'has_saved_key': False}
    assert other_client.get('/console/recipes/providers').json()['deepseek'] == 'environment-model'
    other_client.cookies.clear()
    other_client.headers['Authorization'] = f'Bearer {CONTROL_TOKEN}'
    assert other_client.get(path).status_code == 401
    assert other_client.patch(path, json={'deepseek_key': secret}).status_code == 401
