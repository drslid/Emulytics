import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_HARDWARE, hardwareEditable, hardwarePresets, parseHardware, sameAppliedHardware, sameHardware } from "../lib/emulator-hardware.ts";
import { hardwareCopy, hardwareStorageCopy } from "../lib/emulator-hardware-copy.ts";
import { parseEmulatorCreation } from "../lib/emulators.ts";

test("hardware presets fit the same display and resource bounds as the backend", () => {
  for (const settings of Object.values(hardwarePresets)) assert.deepEqual(parseHardware(settings), settings);
  for (const change of [{ram_mb:true}, {ram_mb:"2048"}, {ram_mb:9000}, {ram_mb:1100}, {cpu_cores:9}, {width:721}, {height:4000}, {density:50}, {storage_gb:1}, {storage_gb:65}, {shell:"reboot"}]) {
    assert.equal(parseHardware({...DEFAULT_HARDWARE,...change}), null);
  }
});
test("a retried emulator creation preserves its hardware and still accepts legacy intents", () => {
  const request = { name:"Phone",host_id:"host-one",application_ids:["chrome"],idempotency_key:"00000000-0000-4000-8000-000000000001" };
  assert.deepEqual(parseEmulatorCreation(request), request);
  assert.deepEqual(parseEmulatorCreation({...request,hardware:hardwarePresets.balanced}), {...request,hardware:hardwarePresets.balanced});
  assert.equal(parseEmulatorCreation({...request,hardware:{...DEFAULT_HARDWARE,cpu_cores:999}}), null);
});
test("hardware editing never suggests changing a running, leased or queued emulator", () => {
  const emulator = {state:"stopped",availability:"declared",operation_status:"succeeded"};
  assert.equal(hardwareEditable(emulator),true);
  assert.equal(hardwareEditable({...emulator,state:"created"}),true);
  for (const state of ["running","ready","unknown","failed","starting","preparing"]) assert.equal(hardwareEditable({...emulator,state}),false);
  for (const availability of ["busy","needs_review"]) assert.equal(hardwareEditable({...emulator,availability}),false);
  assert.equal(hardwareEditable({...emulator,operation_status:"queued"}),false);
  assert.equal(sameHardware(DEFAULT_HARDWARE,{...DEFAULT_HARDWARE}),true);
  assert.equal(sameHardware(DEFAULT_HARDWARE,{...DEFAULT_HARDWARE,ram_mb:2048}),false);
});
test("all ten hardware languages cover every visible label and preservation rule", () => {
  assert.equal(Object.keys(hardwareCopy).length,10);
  for (const copy of Object.values(hardwareCopy)) {
    assert.deepEqual(Object.keys(copy).sort(),Object.keys(hardwareCopy.en).sort());
    for (const value of Object.values(copy)) assert.ok(typeof value === "string" && value.trim());
  }
});
test("measured or unknown legacy storage never creates a permanent pending hardware state",()=>{
  const {storage_gb,...flags}=DEFAULT_HARDWARE;
  for(const storage_capacity_bytes of [null,6000000*1024,8125880*1024]) {
    assert.equal(sameAppliedHardware(DEFAULT_HARDWARE,{...flags,storage_capacity_bytes}),true);
    assert.equal(sameAppliedHardware({...DEFAULT_HARDWARE,ram_mb:2048},{...flags,storage_capacity_bytes}),false);
  }
  for(const locale of Object.keys(hardwareCopy)) for(const key of ["initial","observed","unknown","flags"]) assert.ok(hardwareStorageCopy[locale][key]);
});
