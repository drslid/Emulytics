"""Compile goals into reviewed driver capabilities; generation never executes actions."""
import copy
import json
from pathlib import Path
import re
from urllib.parse import quote

from fastapi import HTTPException
from pydantic import ValidationError

from .android_driver import AndroidDriver, DriverError
from .automation_models import RecipeInput

TEMPLATE = Path(__file__).with_name('workflow_templates') / 'wikipedia.json'
WIKI = r'wikip[eé]dia'
VERIFY = r'(?:\s*(?:,?\s*(?:et|and)\s+)(?:v[eé]rifie(?:r)?|verify|check)\s+(?:le\s+|the\s+)?(?:r[eé]sultat|titre de l[’\']article|article|result))?'
PATTERNS = [
    rf'(?:(?:ouvre|ouvrir|open)\s+chrome\s*[,;]\s*)?(?:(?:va|aller|go)\s+(?:sur|to)\s+|(?:ouvre|ouvrir|open)\s+)?{WIKI}\s*[,;]\s*(?:recherche(?:r)?|search(?: for)?)\s+(?P<query>.+?){VERIFY}',
    rf'(?:recherche(?:r)?|search(?: for)?)\s+(?P<query>.+?)\s+(?:sur|on)\s+{WIKI}{VERIFY}',
]


def validate_generated_recipe(value, instructions):
    try:
        value = copy.deepcopy(value)
        value['instructions'] = instructions
        recipe = RecipeInput.model_validate(value)
        if recipe.recovery_budget or any(step.recovery_budget for step in recipe.steps):
            raise ValueError('Generated recovery is not enabled')
        for step in recipe.steps:
            row = step.model_dump(mode='json', by_alias=True)
            AndroidDriver.validate_step(row)
            if step.action == 'ensure_package' and (step.args.get('apk') or step.args.get('sha256')):
                raise ValueError('Generated artifact paths are not trusted')
        return recipe.model_dump(mode='json', by_alias=True)
    except (ValidationError, DriverError, ValueError, TypeError, KeyError):
        raise HTTPException(422, 'Le parcours généré dépasse les capacités du moteur. Précisez votre objectif ou utilisez les réglages avancés.') from None


def local_goal(instructions):
    """Recognize complete reference intents only; never drop an extra requested action."""
    source = instructions.strip().rstrip('.').strip()
    match = next((m for pattern in PATTERNS if (m := re.fullmatch(pattern, source, re.IGNORECASE))), None)
    if not match:
        return None
    query = match['query'].strip()
    quoted = len(query) >= 2 and (query[0], query[-1]) in [('«', '»'), ('"', '"'), ('“', '”'), ("'", "'")]
    if quoted:
        query = query[1:-1].strip()
    elif query.lower() in ('le football', 'le basketball'):
        query = query[3:]
    if (not query or len(query) > 120 or any(ord(c) < 32 for c in query)
            or (not quoted and re.search(r'\b(?:et|puis|ensuite|and|then|verify|v[eé]rifie(?:r)?)\b|[,;<>]', query, re.I))):
        return None
    title = query[0].upper() + query[1:]
    template = json.loads(TEMPLATE.read_text())
    def replace(value):
        if isinstance(value, str):
            return re.sub(r'football|Football', lambda match: query if match[0] == 'football' else title, value)
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {key: item.replace('football', 'query') if key == 'id' else replace(item) for key, item in value.items()}
        return value
    steps = replace(template['steps'])
    # URL navigation supports Unicode without inventing an Android keyboard input method.
    if not query.isascii() or '%s' in query:
        final = copy.deepcopy(steps[-1])
        steps = steps[:6] + [{
            'id': 'search-wikipedia', 'action': 'open_url',
            'args': {'url': 'https://fr.wikipedia.org/wiki/Special:Search?search=' + quote(query, safe='')},
            'timeout_ms': 30000, 'assert': final['assert'],
        }, final]
    def encode_paths(value):
        if isinstance(value, dict):
            return {key: quote(item.replace(' ', '_'), safe='/_') if key == 'path_contains' else encode_paths(item) for key, item in value.items()}
        if isinstance(value, list):
            return [encode_paths(item) for item in value]
        return value
    recipe = validate_generated_recipe({
        'name': f'Wikipédia · {query}'[:120], 'steps': encode_paths(steps), 'recovery_budget': 0,
    }, instructions)
    return {'recipe': recipe, 'source': 'verified_template', 'query': query,
            'expected_result': title, 'capabilities': ['chrome', 'wikipedia'],
            'requires_test': True}
