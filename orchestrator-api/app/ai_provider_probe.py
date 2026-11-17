"""Run provider connectivity checks without exposing upstream responses."""

import json
import threading
import time

from fastapi import HTTPException
import httpx


_SHARED_PROBES = threading.BoundedSemaphore(2)


def _ollama_tag(name):
    return name if ':' in name.rsplit('/', 1)[-1] else name + ':latest'


def probe_shared_model(provider, settings):
    if not settings:
        raise HTTPException(409, {'code': 'provider_unconfigured'})
    if not _SHARED_PROBES.acquire(blocking=False):
        raise HTTPException(429, {'code': 'provider_busy'})
    try:
        local = provider == 'ollama'
        url = settings['url'].copy_with(path='/api/tags') if local else 'https://api.deepseek.com/models'
        headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity', **settings['headers']}
        configured = _ollama_tag(settings['model']) if local else settings['model']
        deadline = time.monotonic() + 8
        body = bytearray()
        with httpx.stream('GET', url, headers=headers, timeout=httpx.Timeout(8, connect=3),
                          trust_env=False, follow_redirects=False) as response:
            if response.status_code in (401, 403):
                raise HTTPException(422, {'code': 'provider_auth_failed'})
            if response.status_code == 429:
                raise HTTPException(429, {'code': 'provider_busy'})
            response.raise_for_status()
            for chunk in response.iter_raw():
                if time.monotonic() > deadline:
                    raise TimeoutError
                if len(body) + len(chunk) > 524288:
                    raise ValueError('Model list too large')
                body.extend(chunk)
        data = json.loads(body)
        models = data['models' if local else 'data']
        if not isinstance(models, list):
            raise ValueError('Invalid model list')
        fields = ('name', 'model') if local else ('id',)
        names = (model.get(field) for model in models if isinstance(model, dict) for field in fields)
        if not any((_ollama_tag(name) if local else name) == configured for name in names if isinstance(name, str)):
            raise HTTPException(422, {'code': 'provider_model_unavailable'})
    except (httpx.TimeoutException, TimeoutError):
        raise HTTPException(504, {'code': 'provider_timeout'}) from None
    except (httpx.HTTPError, KeyError, TypeError, ValueError, RecursionError):
        raise HTTPException(503, {'code': 'provider_unavailable'}) from None
    finally:
        _SHARED_PROBES.release()


def probe_openai(config, session):
    from .journey_provider import JourneyProvider

    try:
        JourneyProvider(config).test_openai(session)
    except HTTPException as error:
        codes = {429: 'provider_busy', 503: 'provider_unavailable', 504: 'provider_timeout'}
        if error.status_code not in codes:
            raise
        raise HTTPException(error.status_code, {'code': codes[error.status_code]}) from None
