import assert from "node:assert/strict";
import { test } from "node:test";
import { canSubmitDevices, isDeviceReady } from "../lib/device-readiness.ts";
const connected = { device_id: "emulator", availability: "declared", connection_status: "connected" };

test("an immediate launch requires observed Android readiness for every target", () => {
  assert.equal(canSubmitDevices(["emulator"], [connected]), true);
  for (const state of [undefined, "worker_offline", "not_connected", "unauthorized", "offline", "unknown"]) {
    const unavailable = { ...connected, connection_status: state };
    assert.equal(isDeviceReady(unavailable), false, String(state));
    assert.equal(canSubmitDevices(["emulator"], [unavailable]), false, String(state));
  }
  assert.equal(canSubmitDevices([], [connected]), false);
  assert.equal(canSubmitDevices(["missing"], [connected]), false);
  assert.equal(canSubmitDevices(["emulator", "missing"], [connected]), false);
  assert.equal(isDeviceReady({ ...connected, availability: "needs_review" }), false);
  assert.equal(isDeviceReady({ ...connected, availability: "busy" }), true);
});

test("an uncertain submitted request stays replayable after loss of connection or quarantine", () => {
  for (const devices of [[], [{ ...connected, connection_status: "worker_offline" }], [{ ...connected, availability: "needs_review" }]])
    assert.equal(canSubmitDevices(["emulator"], devices, true), true);
});
