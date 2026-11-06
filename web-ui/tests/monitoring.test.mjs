import assert from 'node:assert/strict';
import { test } from 'node:test';
import { currentSignals, signalIsFresh, streamIsFresh } from '../lib/monitoring.ts';

test('a silent SSE stream expires even without a browser connection error', () => {
  assert.equal(streamIsFresh(null, 100), false);
  assert.equal(streamIsFresh(100, 10_100), true);
  assert.equal(streamIsFresh(100, 10_101), false);
  assert.equal(streamIsFresh(100, 99), false);
  assert.equal(streamIsFresh(NaN, 100), false);
});
test('heartbeat age keeps advancing between snapshots and unhealthy signals stay unconfirmed', () => {
  const signal = { live: true, status: 'ready', age_seconds: 18 };
  assert.equal(signalIsFresh(signal, 1, 20), true);
  assert.equal(signalIsFresh(signal, 2, 20), false);
  assert.equal(signalIsFresh({ ...signal, status: 'failed' }, 0, 20), false);
  assert.equal(signalIsFresh({ ...signal, age_seconds: null }, 0, 20), false);
});
test('replaced instances do not look like current outages and multiple live workers remain visible', () => {
  const service = (component, instance_id, live, last_seen_at) => ({ component, instance_id, live, last_seen_at });
  const services = [service('api', 'old-api', false, '2026-11-01'), service('api', 'new-api', true, '2026-11-06'),
    service('worker', 'worker-a', true, '2026-11-06'), service('worker', 'worker-b', true, '2026-11-06'),
    service('scheduler', 'old', false, '2026-11-01'), service('scheduler', 'latest', false, '2026-11-05')];
  assert.deepEqual(currentSignals(services).map(s => s.instance_id), ['new-api', 'worker-a', 'worker-b', 'latest']);
  assert.equal(services.length, 6);
});
