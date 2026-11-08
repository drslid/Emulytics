"""The stdio MCP transport delegates to the scoped API and never executes device commands."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / 'scripts' / 'emulytix-mcp.py'
spec = importlib.util.spec_from_file_location('emulytix_mcp', MODULE_PATH)
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


class FakeAPI:
    def __init__(self):
        self.calls = []

    def call(self, method, endpoint, values=None):
        self.calls.append((method, endpoint, values))
        return {'scopes': ['devices.read', 'runs.read']} if endpoint == '/capabilities' else {'items': []}


def request(method, params=None, request_id=1):
    return {'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params or {}}


def ready_server():
    api = FakeAPI()
    server = mcp.Server(api)
    response = server.handle(request('initialize', {'protocolVersion': mcp.PROTOCOL, 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}))
    assert response['result']['protocolVersion'] == mcp.PROTOCOL
    assert server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) is None
    return server, api


def test_mcp_lifecycle_and_scoped_tools():
    raw = mcp.Server(FakeAPI())
    raw.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
    assert raw.handle(request('tools/list'))['error']['code'] == -32000
    server, api = ready_server()
    result = server.handle(request('tools/list'))['result']
    names = [tool['name'] for tool in result['tools']]
    assert names == ['list_devices', 'list_runs', 'get_run', 'get_run_events']
    assert 'start_run' not in names
    assert server.handle(request('ping'))['result'] == {}
    assert server.handle(request('missing'))['error']['code'] == -32601
    assert server.handle(request('initialize'))['error']['code'] == -32600


def test_mcp_calls_preserve_client_key_and_do_not_auto_retry():
    server, api = ready_server()
    args = {'workflow_id': 'test', 'workflow_version': 1, 'device_ids': ['phone'], 'max_concurrency': 1,
            'idempotency_key': 'preserve-this-request'}
    response = server.handle(request('tools/call', {'name': 'start_run', 'arguments': args}))
    assert not response['result']['isError']
    assert api.calls == [('POST', '/runs', args)]
    response = server.handle(request('tools/call', {'name': 'list_runs', 'arguments': {'offset': 100}}))
    assert api.calls[-1] == ('GET', '/runs', {'limit': 30, 'offset': 100})
    assert response['result']['structuredContent'] == {'items': []}


@pytest.mark.parametrize('name,args', [
    ('get_run', {'run_id': '../../console/users'}), ('list_runs', {'limit': 101}),
    ('list_runs', {'limit': True}), ('list_devices', {'url': 'http://169.254.169.254/'}),
    ('start_run', {'idempotency_key': 'missing required fields'}),
])
def test_mcp_rejects_invalid_arguments_without_http(name, args):
    server, api = ready_server()
    result = server.handle(request('tools/call', {'name': name, 'arguments': args}))['result']
    assert result['isError'] and api.calls == []


def test_mcp_stdio_has_only_json_rpc_on_stdout_and_no_secret():
    secret = 'emk_'+'A'*43
    init = request('initialize', {'protocolVersion': mcp.PROTOCOL, 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}})
    messages = '\n'.join([json.dumps(init), '{invalid', json.dumps(request('ping', request_id='ping'))])+'\n'
    import os
    result = subprocess.run([sys.executable, str(MODULE_PATH)], input=messages, text=True, capture_output=True,
                            env={**os.environ, 'EMULYTIX_API_URL': 'http://localhost:3100', 'EMULYTIX_API_KEY': secret}, timeout=10)
    assert result.returncode == 0
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses[1]['error']['code'] == -32700 and responses[2]['id'] == 'ping'
    assert secret not in result.stdout+result.stderr


@pytest.mark.parametrize('url', ['http://remote.test', 'https://user:pass@remote.test', 'https://remote.test/?key=x', 'https://remote.test/console/users'])
def test_mcp_configuration_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        mcp.API(url, 'emk_'+'A'*43)
