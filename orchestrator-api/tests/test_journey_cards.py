import json

from fastapi import HTTPException, Request
import pytest
from pydantic import ValidationError

from app import automation_routes, journey_cards, journey_context
from app.access import required_permission
from app.automation_models import CardPreparation, GoalInput


EXAMPLE = "Ouvre les paramètres du téléphone, prends une capture d’écran et récupère la version Android."


def card(card_id, instruction, verification=None):
    return {'id': card_id, 'instruction': instruction, 'verification': verification}


def request(user=None):
    return Request({'type': 'http', 'state': {'auth_user': user}})


def test_known_legacy_and_capture_goals_compile_without_a_provider(monkeypatch):
    monkeypatch.setattr(automation_routes, '_generate_draft', lambda *_, **__: pytest.fail('No provider for a known reference'))
    cards = automation_routes.suggest_cards(GoalInput(instructions=EXAMPLE), request(), None)['cards']
    assert [item['instruction'] for item in cards] == [
        "Ouvre les paramètres du téléphone", "prends une capture d’écran", "récupère la version Android.",
    ]
    reply = automation_routes.prepare_cards(CardPreparation(name='Mon parcours', cards=[
        {'id': f'card-{index}', **value} for index, value in enumerate(cards)
    ]), request(), None)
    assert reply['recipe']['name'] == 'Mon parcours'
    assert reply['source'] == 'verified_template' and reply['requires_test']
    assert [step['action'] for step in reply['recipe']['steps']] == ['open_settings', 'screenshot', 'read_device_info']
    assert 'cards' not in reply['recipe']
    assert all(step['assert']['value'] == 'com.android.settings' for step in reply['recipe']['steps'])


def test_capture_of_version_uses_about_and_a_real_observation():
    reply = automation_routes.prepare_cards(CardPreparation(cards=[
        card('version', 'Dans les paramètres, prends une capture d’écran de la version d’Android.',
             'La version Android est relevée.')
    ]), request(), None)
    assert reply['recipe']['steps'][-2]['args'] == {'section': 'about'}
    assert reply['recipe']['steps'][-1]['action'] == 'read_device_info'


def test_legacy_android_reference_keeps_foreground_for_next_card():
    reply = automation_routes.prepare_cards(CardPreparation(cards=[
        card('version', 'Tell me the Android version of my device'),
        card('capture', 'Take a screenshot'),
    ]), request(), None)
    assert reply['recipe']['steps'][-1]['assert']['value'] == 'com.android.settings'


def test_english_reference_can_record_version_and_api_level():
    reply = automation_routes.prepare_cards(CardPreparation(cards=[
        card('version', 'Read the Android version', 'Record the Android version and API level'),
    ]), request(), None)
    assert reply['source'] == 'verified_template'
    assert reply['recipe']['steps'][-1]['args'] == {'field': 'android_version'}


def test_cards_resolve_exact_known_app_aliases_and_preserve_package_case():
    reply = automation_routes.prepare_cards(CardPreparation(cards=[
        card('linkedin', 'Ouvre LinkedIn', 'Vérifie que LinkedIn est ouvert.'),
        card('literal', 'Ouvre com.Example.App', 'com.Example.App est au premier plan.'),
    ]), request(), None)
    assert [step['args']['package_name'] for step in reply['recipe']['steps']] == [
        'com.linkedin.android', 'com.Example.App',
    ]


@pytest.mark.parametrize('bad, message', [
    (card('second', 'Prends une capture d’écran'), journey_cards.CLARIFY_CAPTURE),
    (card('second', 'Ouvre les paramètres et réinitialise le téléphone.'), journey_cards.UNSUPPORTED_ACTION),
    (card('second', 'Relève la version Android', 'Confirme que la version d’Android vaut 99.'), journey_cards.CLARIFY_CHECK),
    (card('second', 'Ouvre une application introuvable'), journey_cards.CLARIFY_APP),
])
def test_invalid_cards_get_safe_targeted_clarification_without_inference(monkeypatch, bad, message):
    monkeypatch.setattr(automation_routes, '_generate_draft', lambda *_, **__: pytest.fail('Unsupported request must be clarified'))
    with pytest.raises(HTTPException) as error:
        automation_routes.prepare_cards(CardPreparation(cards=[bad]), request(), None)
    assert error.value.status_code == 422
    assert error.value.detail == {'code': 'card_needs_clarification', 'card_id': 'second', 'message': message}


def test_suggestions_validate_text_only_and_use_the_chosen_provider(monkeypatch):
    def generate(_request, text, provider, *, task):
        assert text == "Obtiens le résultat attendu" and provider == 'ollama'
        assert task is journey_cards.SUGGEST_TASK
        return {'supported': True, 'cards_json': json.dumps([{'instruction': ' Observer ', 'verification': ' ' }])}, provider

    monkeypatch.setattr(automation_routes, '_generate_draft', generate)
    output = automation_routes.suggest_cards(GoalInput(instructions="Obtiens le résultat attendu", provider='ollama'), request(), None)
    assert output == {'cards': [{'instruction': 'Observer', 'verification': None}]}
    with pytest.raises(HTTPException):
        journey_cards.suggested_cards({'supported': True, 'cards_json': '[{"instruction":"Observer","steps":[]}]'})


def test_model_suggestion_uses_friendly_names_and_keeps_urls_and_abbreviations(monkeypatch):
    def generated(*cards):
        return {'supported': True, 'cards_json': json.dumps(cards)}, 'ollama'

    result = generated(dict(instruction='Ouvre com.linkedin.android', verification='com.linkedin.android est visible.'),
                       dict(instruction='Lis p.ex. https://fr.wikipedia.org/wiki/Android, e.g. avec Chrome.'))
    monkeypatch.setattr(automation_routes, '_generate_draft', lambda *_, **__: result)
    payload = GoalInput(instructions='Prépare des vérifications utiles dans Android', provider='ollama')
    assert automation_routes.suggest_cards(payload, request(), None)['cards'] == [
        {'instruction': 'Ouvre LinkedIn', 'verification': 'LinkedIn est visible.'},
        {'instruction': 'Lis p.ex. https://fr.wikipedia.org/wiki/Android, e.g. avec Chrome.', 'verification': None},
    ]
    monkeypatch.setattr(automation_routes, '_generate_draft', lambda *_, **__: generated(dict(instruction='Ouvre org.unknown.app')))
    with pytest.raises(HTTPException) as error:
        automation_routes.suggest_cards(payload, request(), None)
    assert error.value.status_code == 422 and 'org.unknown.app' not in error.value.detail


def test_navigation_cards_still_reach_the_provider(monkeypatch):
    def generate(_request, data, _provider, *, task):
        assert task is journey_cards.PREPARE_TASK
        return {'supported': False, 'card_id': 'page'}, 'ollama'

    monkeypatch.setattr(automation_routes, '_generate_draft', generate)
    with pytest.raises(HTTPException) as error:
        automation_routes.prepare_cards(CardPreparation(cards=[card('page', 'Ouvre la page Android dans Chrome')]), request(), None)
    assert error.value.detail['message'] == journey_cards.CLARIFY_ACTION


def test_prepare_passes_current_cards_and_minimized_verified_context(monkeypatch):
    context = {'device_kind': 'emulator', 'installed_packages': ['com.example.observed'], 'reference_apps': {}}
    monkeypatch.setattr(journey_context, 'journey_context', lambda store, device, instructions: context if device == 'test-device' else {})
    submitted = card('user-card', 'Affiche mon application en cours de vérification.', 'com.example.observed est au premier plan')

    def generate(_request, data, provider, *, task):
        assert data == {'cards': [submitted], 'android': context}
        assert task is journey_cards.PREPARE_TASK and provider == 'deepseek'
        return {'supported': True, 'name': 'Generated name', 'steps_json': json.dumps([
            {'id': submitted['id'], 'steps': [{
                'id': 'open-known-app', 'action': 'open_app', 'args': {'package_name': 'com.example.observed'},
                'assert': {'type': 'package', 'value': 'com.example.observed'},
            }]}
        ])}, provider

    monkeypatch.setattr(automation_routes, '_generate_draft', generate)
    payload = CardPreparation(name='Nom actuel', cards=[submitted], provider='deepseek', device_id='test-device')
    with pytest.raises(HTTPException) as denied:
        automation_routes.prepare_cards(payload, request(), None)
    assert denied.value.status_code == 403
    reply = automation_routes.prepare_cards(payload, request({'permissions': ['devices.read']}), None)
    assert reply['recipe']['name'] == 'Nom actuel'
    assert reply['recipe']['steps'][0]['args']['package_name'] == 'com.example.observed'


@pytest.mark.parametrize('result', [
    {'supported': False, 'card_id': 'requested'},
    {'supported': True, 'steps_json': '[]', 'name': 'Plan'},
    {'supported': True, 'name': 'Plan', 'steps_json': json.dumps([{'id': 'other', 'steps': []}])},
    {'supported': True, 'name': 'Plan', 'steps_json': json.dumps([{'id': 'requested', 'steps': [{
        'id': 'bad', 'action': 'screenshot', 'args': {},
        'assert': {'type': 'package', 'value': 'com.android.chrome'},
    }]}])},
])
def test_prepare_never_accepts_missing_card_intent_or_unverified_result(monkeypatch, result):
    monkeypatch.setattr(automation_routes, '_generate_draft', lambda *_, **__: (result, 'ollama'))
    payload = CardPreparation(cards=[card('requested', 'Observe la fiche appareil.', 'La version Android est relevée.')])
    with pytest.raises(HTTPException) as failure:
        automation_routes.prepare_cards(payload, request(), None)
    assert failure.value.detail['card_id'] == 'requested'


def test_controls_reject_duplicate_cards_and_require_workflow_write():
    with pytest.raises(ValidationError):
        CardPreparation(cards=[card('duplicate', 'Ouvre Chrome'), card('duplicate', 'Prends une capture')])
    for action in ('suggest-cards', 'prepare-cards'):
        path = f'/console/recipes/{action}'
        assert required_permission('POST', path) == 'workflows.write'
        assert required_permission('GET', path) is None


def test_mixed_preparation_preserves_verified_reference_and_provider_group(monkeypatch):
    captured = {'id': 'capture', 'action': 'screenshot', 'args': {},
                'assert': {'type': 'package', 'value': 'com.android.chrome'}}
    monkeypatch.setattr(automation_routes, '_generate_draft', lambda *_, **__: ({
        'supported': True, 'name': 'Wikipédia et capture', 'steps_json': json.dumps([
            {'id': 'search', 'steps': [captured]},
            {'id': 'proof', 'steps': [captured]},
        ]),
    }, 'ollama'))
    payload = CardPreparation(cards=[
        card('search', 'Recherche « Outils, installer Linux » sur Wikipédia'),
        card('proof', 'Immortalise l’état où tu en es.', 'La capture d’écran est jointe.'),
    ])
    steps = automation_routes.prepare_cards(payload, request(), None)['recipe']['steps']
    assert any(step['action'] == 'open_url' for step in steps[:-1])
    assert steps[-1]['action'] == 'screenshot'
    assert len({step['id'] for step in steps}) == len(steps)
