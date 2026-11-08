import assert from "node:assert/strict";
import { test } from "node:test";
import { bulkIntentKey, managedBulkTargets, parseBulkIntent } from "../lib/fleet-groups.ts";
import { fleetCopy } from "../lib/fleet-groups-copy.ts";

test("bulk replay retains the exact action, request key and frozen device order",()=>{
  const intent={request_id:"00000000-0000-4000-8000-000000000001",action:"start",device_ids:["emu-two","emu-one"]};
  assert.deepEqual(parseBulkIntent(JSON.parse(JSON.stringify(intent))),intent);
  assert.equal(bulkIntentKey("alice"),"emulytix-fleet-bulk:alice");
  assert.notEqual(bulkIntentKey("alice"),bulkIntentKey("bob"));
  for(const change of [{action:"reboot"},{request_id:"oops"},{device_ids:[]},{device_ids:["same","same"]},{device_ids:["unsafe; rm"]},{device_ids:Array.from({length:101},(_,i)=>`device-${i}`)},{command:"adb"}]) assert.equal(parseBulkIntent({...intent,...change}),null);
});
test("group power actions use only freshly identified managed emulator ids",()=>{
  assert.deepEqual(managedBulkTargets(["phone","legacy","emu-b","emu-a","emu-a"],["emu-a","emu-b"]),["emu-a","emu-b"]);
  assert.deepEqual(managedBulkTargets(["phone"],[]),[]);
});
test("fleet controls and preservation messages cover the same labels in ten languages",()=>{
  assert.equal(Object.keys(fleetCopy).length,10);
  for(const copy of Object.values(fleetCopy)){
    assert.deepEqual(Object.keys(copy).sort(),Object.keys(fleetCopy.en).sort());
    for(const value of Object.values(copy))assert.ok(typeof value==="string"&&value.trim());
  }
});
