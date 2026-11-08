#!/usr/bin/env python3
"""MCP stdio adapter. All authority and business effects stay in the personal REST API."""
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

PROTOCOL = '2025-11-25'
SUPPORTED_PROTOCOLS = {PROTOCOL, '2025-06-18', '2025-03-26'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class API:
    def __init__(self, url, key):
        parsed = urlparse(url)
        loopback = parsed.hostname in {'localhost', '127.0.0.1', '::1'}
        if (parsed.scheme != 'https' and not (parsed.scheme == 'http' and loopback)) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/', '/api/v1', '/api/v1/'}:
            raise ValueError('Use an HTTPS origin, or HTTP on localhost, for EMULYTIX_API_URL')
        parsed.port
        if not re.fullmatch(r'emk_[A-Za-z0-9_-]{43}', key):
            raise ValueError('Set a personal EMULYTIX_API_KEY')
        self.base = url.rstrip('/')
        if not self.base.endswith('/api/v1'):
            self.base += '/api/v1'
        self.key = key
        self.opener = build_opener(NoRedirect())

    def call(self, method, endpoint, values=None):
        query = '?' + urlencode(values) if method == 'GET' and values else ''
        data = json.dumps(values or {}, ensure_ascii=False, allow_nan=False).encode() if method != 'GET' else None
        request = Request(self.base+endpoint+query, data=data, method=method, headers={
            'Authorization': 'Bearer '+self.key, 'Accept': 'application/json', 'Content-Type': 'application/json',
        })
        try:
            with self.opener.open(request, timeout=20) as response:
                payload = response.read(2_097_153)
                if len(payload) > 2_097_152:
                    raise ValueError('API response too large; reduce the page size')
                return json.loads(payload)
        except HTTPError as exc:
            # Never relay arbitrary upstream bodies, redirects or authentication material.
            raise ValueError({401: 'Personal key expired or revoked', 403: 'Scope or role does not allow this action',
                              404: 'Resource not found', 409: 'Conflict: inspect the existing run before retrying',
                              410: 'Workflow version was removed; choose another published version',
                              422: 'Invalid tool arguments', 429: 'API rate limit reached; retry later'}.get(exc.code, 'Emulytix API unavailable')) from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError):
            raise ValueError('Emulytix API unavailable') from None


def schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


PAGE = {'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100, 'default': 30},
        'offset': {'type': 'integer', 'minimum': 0, 'default': 0}}
RUN_ID = {'type': 'string', 'format': 'uuid'}
TOOLS = {
    'list_devices': ('devices.read', 'List registered devices; registration alone does not prove a live connection.', schema(PAGE)),
    'list_workflows': ('workflows.read', 'List published immutable journey versions.', schema(PAGE)),
    'list_runs': ('runs.read', 'List journey batches and their current status.', schema(PAGE)),
    'get_run': ('runs.read', 'Read a journey batch, its executions and saved evidence.', schema({'run_id': RUN_ID}, ['run_id'])),
    'get_run_events': ('runs.read', 'Read durable events after a sequence number.', schema({'run_id': RUN_ID, 'after': {'type': 'integer', 'minimum': 0}, 'limit': PAGE['limit']}, ['run_id'])),
    'start_run': ('runs.execute', 'Queue a published journey on selected devices. Preserve the same idempotency_key and payload after a timeout; this does not wait for completion.', schema({
        'workflow_id': {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'},
        'workflow_version': {'type': 'integer', 'minimum': 1, 'maximum': 2147483647},
        'device_ids': {'type': 'array', 'items': {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'}, 'minItems': 1, 'maxItems': 100, 'uniqueItems': True},
        'max_concurrency': {'type': 'integer', 'minimum': 1, 'maximum': 100},
        'idempotency_key': {'type': 'string', 'minLength': 1, 'maxLength': 128, 'pattern': '^\\S+$'},
        'parameters': {'type': 'object', 'maxProperties': 64},
    }, ['workflow_id', 'workflow_version', 'device_ids', 'max_concurrency', 'idempotency_key'])),
    'cancel_run': ('runs.cancel', 'Request cancellation of a journey batch. Running actions stop through the worker; inspect status afterward.', schema({'run_id': RUN_ID}, ['run_id'])),
}


def valid_arguments(name, arguments):
    if not isinstance(arguments, dict) or set(arguments) - set(TOOLS[name][2]['properties']) or not set(TOOLS[name][2]['required']) <= set(arguments):
        raise ValueError('Invalid tool arguments')
    for key, value in arguments.items():
        spec = TOOLS[name][2]['properties'][key]
        if spec['type'] == 'integer' and (type(value) is not int or value < spec.get('minimum', 0) or value > spec.get('maximum', 9223372036854775807)):
            raise ValueError('Invalid tool arguments')
        if spec['type'] == 'string':
            if not isinstance(value, str) or not spec.get('minLength', 0) <= len(value) <= spec.get('maxLength', 128) or ('pattern' in spec and not re.fullmatch(spec['pattern'], value)):
                raise ValueError('Invalid tool arguments')
            if spec.get('format') == 'uuid' and not re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', value):
                raise ValueError('Invalid tool arguments')
        if spec['type'] == 'object' and (not isinstance(value, dict) or len(value) > spec.get('maxProperties', 64)):
            raise ValueError('Invalid tool arguments')
        if spec['type'] == 'array':
            if not isinstance(value, list) or not spec['minItems'] <= len(value) <= spec['maxItems'] or any(not isinstance(item, str) or not re.fullmatch(spec['items']['pattern'], item) for item in value) or len(set(value)) != len(value):
                raise ValueError('Invalid tool arguments')
    if name == 'start_run' and arguments['max_concurrency'] > len(arguments['device_ids']):
        raise ValueError('Concurrency cannot exceed the device count')


class Server:
    def __init__(self, api):
        self.api = api
        self.initialized = False
        self.initialization_sent = False

    @staticmethod
    def error(request_id, code, message):
        return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}

    def handle(self, message):
        if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str) or ('id' in message and (isinstance(message['id'], bool) or not isinstance(message['id'], (str, int)))):
            return self.error(None, -32600, 'Invalid Request')
        method, request_id = message['method'], message.get('id')
        params = message.get('params', {})
        if not isinstance(params, dict):
            return self.error(request_id, -32602, 'Invalid params') if 'id' in message else None
        if 'id' not in message:
            if method == 'notifications/initialized' and self.initialization_sent:
                self.initialized = True
            return None
        if method == 'initialize':
            if self.initialization_sent:
                return self.error(request_id, -32600, 'Connection already initialized')
            client = params.get('clientInfo', {})
            if not isinstance(params.get('protocolVersion'), str) or not isinstance(params.get('capabilities'), dict) or not isinstance(client, dict) or not isinstance(client.get('name'), str) or not isinstance(client.get('version'), str):
                return self.error(request_id, -32602, 'Invalid initialization')
            self.initialization_sent = True
            result = {'protocolVersion': params['protocolVersion'] if params['protocolVersion'] in SUPPORTED_PROTOCOLS else PROTOCOL,
                      'capabilities': {'tools': {}}, 'serverInfo': {'name': 'emulytix', 'version': '0.1.0'},
                      'instructions': 'Use only listed tools. Keep a run idempotency key stable after uncertain delivery. Device registration is not proof of readiness.'}
        elif method == 'ping':
            result = {}
        elif not self.initialized:
            return self.error(request_id, -32000, 'Initialize the connection first')
        elif method == 'tools/list':
            if params:
                return self.error(request_id, -32602, 'No pagination cursor is required')
            try:
                scopes = self.api.call('GET', '/capabilities')['scopes']
            except (ValueError, KeyError, TypeError):
                return self.error(request_id, -32000, 'Personal API unavailable; verify the key and origin')
            result = {'tools': [{'name': name, 'description': description, 'inputSchema': definition,
                                 'annotations': {'readOnlyHint': name not in {'start_run', 'cancel_run'},
                                                 'destructiveHint': name == 'cancel_run', 'idempotentHint': True, 'openWorldHint': name == 'start_run'}}
                                for name, (scope, description, definition) in TOOLS.items() if scope in scopes]}
        elif method == 'tools/call':
            if set(params) - {'name', 'arguments'}:
                return self.error(request_id, -32602, 'Invalid params')
            name, arguments = params.get('name'), params.get('arguments', {})
            if not isinstance(name, str) or name not in TOOLS:
                return self.error(request_id, -32602, 'Unknown tool')
            try:
                valid_arguments(name, arguments)
                if name.startswith('list_'):
                    value = self.api.call('GET', '/'+name[5:], {'limit': 30, **arguments})
                elif name == 'start_run':
                    value = self.api.call('POST', '/runs', arguments)
                else:
                    path = '/runs/'+arguments['run_id']
                    if name == 'cancel_run':
                        value = self.api.call('POST', path+'/cancel', {})
                    else:
                        value = self.api.call('GET', path+('/events' if name == 'get_run_events' else ''), {key: value for key, value in arguments.items() if key != 'run_id'})
                result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False, allow_nan=False)}], 'structuredContent': value, 'isError': False}
            except (ValueError, KeyError, TypeError) as exc:
                result = {'content': [{'type': 'text', 'text': str(exc) if isinstance(exc, ValueError) else 'Invalid API response'}], 'isError': True}
        else:
            return self.error(request_id, -32601, 'Method not found')
        return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def main():
    try:
        server = Server(API(os.environ.get('EMULYTIX_API_URL', 'http://localhost:3100'), os.environ.get('EMULYTIX_API_KEY', '')))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    while True:
        raw = sys.stdin.buffer.readline(65_538)
        if not raw:
            return 0
        if len(raw) > 65_536:
            print(json.dumps(Server.error(None, -32600, 'Request too large')), flush=True)
            return 1
        try:
            message = json.loads(raw.decode('utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid number')))
            response = server.handle(message)
        except (UnicodeDecodeError, ValueError, RecursionError):
            response = Server.error(None, -32700, 'Parse error')
        if response is not None:
            print(json.dumps(response, ensure_ascii=False, allow_nan=False), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
