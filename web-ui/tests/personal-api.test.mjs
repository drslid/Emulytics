import assert from 'node:assert/strict';
import { test } from 'node:test';
import { keyActive, initialKeyScopes, selectedKeyScopes } from '../lib/personal-api.ts';
import { apiKeyText } from '../lib/personal-api-i18n.ts';

test('personal key presets never request unavailable role scopes', () => {
  const read = ['devices.read', 'workflows.read', 'runs.read'];
  assert.deepEqual(initialKeyScopes(read), read);
  assert.deepEqual(selectedKeyScopes('publish', read), read);
  const builder = [...read, 'runs.execute', 'runs.cancel', 'workflows.publish', 'users.manage'];
  assert.deepEqual(selectedKeyScopes('publish', builder), builder.slice(0, -1));
  assert.equal(selectedKeyScopes('read', builder).includes('runs.execute'), false);
});

test('expiration and revocation both disable personal key actions', () => {
  const key = { revoked_at: null, expires_at: '2026-11-09T00:00:00Z' };
  assert.equal(keyActive(key, Date.parse('2026-11-08T00:00:00Z')), true);
  assert.equal(keyActive(key, Date.parse(key.expires_at)), false);
  assert.equal(keyActive({ ...key, revoked_at: '2026-11-07T00:00:00Z' }, 0), false);
});

test('personal key interface copy covers the ten target languages', () => {
  for (const locale of ['en', 'fr', 'zh', 'hi', 'es', 'pt', 'ar', 'ru', 'bn', 'de'])
    for (const key of ['title', 'intro', 'create', 'name', 'purpose', 'read', 'run', 'publish', 'expires', 'password', 'code', 'once', 'saved', 'copy', 'copied', 'close', 'cancel', 'revoke', 'revokeHelp', 'empty', 'active', 'expired', 'revoked', 'validUntil', 'lastUsed', 'never', 'loading', 'retry', 'previous', 'next', 'failed', 'rejected', 'uncertain', 'scopes', 'instructions'])
      assert.ok(apiKeyText(locale, key).trim(), `${locale}:${key}`);
  assert.equal(apiKeyText('fr', 'create'), 'Créer une clé');
});
