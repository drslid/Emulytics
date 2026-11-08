import assert from 'node:assert/strict';
import { test } from 'node:test';
import { proxyPersonalAPI } from '../lib/personal-api-proxy.ts';

process.env.EMULYTIX_API_INTERNAL_URL = 'http://api.internal:8010';
process.env.EMULYTIX_PUBLIC_ORIGIN = 'http://localhost:3100';
const token = 'emk_'+'A'.repeat(43);
const url = 'http://localhost:3100/api/v1/';

test('personal API proxy forwards only the bearer, known paths and bounded query', async () => {
  const request = new Request(url+'runs?limit=30&offset=10&token=forbidden', { headers: { Authorization: 'Bearer '+token, Cookie: 'emulytix_session=never-forward' } });
  const response = await proxyPersonalAPI(request, ['runs'], async (target, options) => {
    assert.equal(target, 'http://api.internal:8010/api/v1/runs?limit=30&offset=10');
    assert.equal(options.headers.get('Authorization'), 'Bearer '+token);
    assert.equal(options.headers.get('Cookie'), null);
    assert.equal(options.redirect, 'error');
    return Response.json({ items: [] }, { headers: { 'Set-Cookie': 'forbidden=secret' } });
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('set-cookie'), null);
  assert.equal(response.headers.get('Cache-Control'), 'private, no-store');
});

test('personal API proxy rejects sessions, service tokens, origins and private endpoints', async () => {
  const never = () => assert.fail('Must fail before contacting the backend');
  for (const authorization of ['', 'Bearer service-token'])
    assert.equal((await proxyPersonalAPI(new Request(url+'devices', { headers: { Authorization: authorization, Cookie: 'emulytix_session=valid' } }), ['devices'], never)).status, 401);
  assert.equal((await proxyPersonalAPI(new Request(url+'devices', { headers: { Authorization: 'Bearer '+token, Origin: 'https://evil.test' } }), ['devices'], never)).status, 403);
  for (const path of ['console/users', 'auth/me', 'devices/phone/exec', 'runs/../../auth/me'])
    assert.equal((await proxyPersonalAPI(new Request(url+path, { headers: { Authorization: 'Bearer '+token } }), path.split('/'), never)).status, 404);
});

test('personal API proxy bounds JSON writes and preserves retry status', async () => {
  const request = (body) => new Request(url+'runs', { method: 'POST', body, headers: { Authorization: 'Bearer '+token, 'Content-Type': 'application/json' } });
  assert.equal((await proxyPersonalAPI(request('x'.repeat(65537)), ['runs'], () => assert.fail('Oversized body'))).status, 413);
  const response = await proxyPersonalAPI(request('{}'), ['runs'], async (_, options) => {
    assert.equal(new TextDecoder().decode(options.body), '{}');
    return Response.json({ detail: 'limited' }, { status: 429, headers: { 'Retry-After': '60' } });
  });
  assert.equal(response.status, 429);
  assert.equal(response.headers.get('retry-after'), '60');
});
