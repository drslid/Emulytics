import assert from "node:assert/strict";
import { test } from "node:test";
import { canSubmitDevices, connectionWorkerHosts, isDeviceReady } from "../lib/device-readiness.ts";
const connected = { device_id: "emulator", availability: "declared", connection_status: "connected" };

test("new devices use active worker hosts rather than historical device declarations", () => {
  const devices = [
    {...connected, host_id: "bench-host"},
    {...connected, device_id: "legacy", host_id: "bench", connection_status: "worker_offline"},
    {...connected, device_id: "legacy-api", host_id: "unverified", connection_status: undefined},
  ];
  assert.deepEqual(connectionWorkerHosts(devices), ["bench-host"]);
  assert.deepEqual(connectionWorkerHosts([], ["new-host", "new-host"]), ["new-host"]);
  assert.deepEqual(connectionWorkerHosts(devices, []), []);
  assert.deepEqual(connectionWorkerHosts(devices, ["other-host"]), ["other-host"]);
  assert.deepEqual(connectionWorkerHosts([{...devices[0], connection_status:"not_connected"}]), ["bench-host"]);
});

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
  assert.equal(isDeviceReady({...connected,emulator_state:"ready"}),true);
  for(const emulator_state of ["created","running","starting","stopped","preparing","failed","unknown"])
    assert.equal(isDeviceReady({...connected,emulator_state}),false,emulator_state);
});

test("an uncertain submitted request stays replayable after loss of connection or quarantine", () => {
  for (const devices of [[], [{ ...connected, connection_status: "worker_offline" }], [{ ...connected, availability: "needs_review" }]])
    assert.equal(canSubmitDevices(["emulator"], devices, true), true);
});
