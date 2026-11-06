import assert from "node:assert/strict";
import { test } from "node:test";
import { canonicalizeEmulatorUpload, currentEmulatorLaunchDevice, emulatorCanLaunch, emulatorCanManage, emulatorConnectionDevice, emulatorIntentKey, emulatorOperationActive, mergeEmulatorLaunchDevices, missingEmulatorApplications, parseEmulatorCreation, parseEmulatorOperation } from "../lib/emulators.ts";
import { isDeviceReady } from "../lib/device-readiness.ts";

const emulator = {state:"ready",availability:"declared",operation_status:null,application_ids:[]};
const key = "00000000-0000-4000-8000-000000000001";

test("uploading a selected or unselected preset keeps its canonical catalog id visible and available",()=>{
  const snapchat={id:"snapchat",name:"Snapchat",package_name:"com.snapchat.android",source:"apk",available:false,size_bytes:0};
  const uploaded={...snapchat,id:key,name:"Uploaded label",available:true,size_bytes:1234};
  for(const selected of [["chrome","snapchat"],["chrome"]]){
    const result=canonicalizeEmulatorUpload(uploaded,[snapchat],selected);
    assert.deepEqual(result.application,{...uploaded,id:"snapchat",name:"Snapchat"});
    assert.deepEqual(result.selected,["chrome","snapchat"]);
    assert.deepEqual(missingEmulatorApplications(result.selected,[{id:"chrome",available:true},result.application]),[]);
  }
  const old={...uploaded,id:"00000000-0000-4000-8000-000000000002"};
  assert.deepEqual(canonicalizeEmulatorUpload(uploaded,[snapchat,old],["snapchat",old.id,key,"chrome"]).selected,["snapchat","chrome"]);
});

test("a custom APK replaces a selected older APK of the same package without masquerading as a preset",()=>{
  const older={id:key,name:"Custom app",package_name:"com.emulytix.custom",source:"apk",available:true,size_bytes:10};
  const uploaded={...older,id:"00000000-0000-4000-8000-000000000002",size_bytes:20};
  assert.deepEqual(canonicalizeEmulatorUpload(uploaded,[older],[key,"chrome"]),{application:uploaded,selected:[uploaded.id,"chrome"]});
});

test("a managed emulator carries its actual device outside the paginated inventory without inventing readiness",()=>{
  const device={device_id:"managed",connection_status:"connected",availability:"declared",worker_last_seen_at:"2026-11-06T20:00:05Z"};
  const managed={...emulator,device_id:"managed",device};
  assert.equal(emulatorConnectionDevice(managed,[]),device);
  assert.equal(emulatorConnectionDevice({...managed,device:undefined},[]),undefined);
  assert.equal(emulatorConnectionDevice({...managed,device:{...device,device_id:"another"}},[]),undefined);
  const merged=mergeEmulatorLaunchDevices([{device_id:"other"}],device);
  assert.equal(merged[0],device);assert.equal(merged.length,2);
  const stale={...device,connection_status:"not_connected",worker_last_seen_at:"2026-11-06T20:00:00Z"};
  assert.equal(mergeEmulatorLaunchDevices([stale],device)[0],device);
  const current={...device,connection_status:"worker_offline",worker_last_seen_at:"2026-11-06T20:00:10Z"};
  assert.equal(mergeEmulatorLaunchDevices([current,current],device)[0],current);
  assert.equal(mergeEmulatorLaunchDevices([current,current],device).length,1);
});

test("an off-page launch follows fresh managed observations instead of keeping a connected snapshot forever",()=>{
  const initial={device_id:"managed",connection_status:"connected",availability:"declared",worker_last_seen_at:"2026-11-06T20:00:00Z"};
  const disconnected={...initial,connection_status:"worker_offline"};
  assert.equal(currentEmulatorLaunchDevice(initial,[disconnected]),disconnected);
  assert.equal(isDeviceReady(mergeEmulatorLaunchDevices([],currentEmulatorLaunchDevice(initial,[disconnected]))[0]),false);
  assert.equal(currentEmulatorLaunchDevice(initial,[]).connection_status,"unknown");
  assert.equal(currentEmulatorLaunchDevice(undefined,[disconnected]),undefined);
});

test("runtime changes require an idle unquarantined emulator and respect its lifecycle",()=>{
  assert.equal(emulatorCanManage(emulator,"prepare"),true);assert.equal(emulatorCanManage(emulator,"stop"),true);assert.equal(emulatorCanManage(emulator,"start"),false);
  for(const state of ["created","stopped"]){assert.equal(emulatorCanManage({...emulator,state},"start"),true);assert.equal(emulatorCanManage({...emulator,state},"stop"),false);assert.equal(emulatorCanManage({...emulator,state},"prepare"),true);}
  assert.equal(emulatorOperationActive({...emulator,state:"running"}),false);
  assert.equal(emulatorCanManage({...emulator,state:"running"},"start"),false);
  for(const state of ["running","unknown","failed"])for(const action of ["stop","prepare"])assert.equal(emulatorCanManage({...emulator,state},action),true);
  for(const availability of ["busy","needs_review"])for(const action of ["start","prepare","stop"])assert.equal(emulatorCanManage({...emulator,availability},action),false);
  for(const operation_status of ["queued","running","waiting_auth"]){assert.equal(emulatorOperationActive({...emulator,operation_status}),true);assert.equal(emulatorCanManage({...emulator,operation_status},"stop"),false);}
});
test("launch readiness requires preparation and real Android evidence without replacing normal queue serialization",()=>{
  const device={connection_status:"connected",availability:"declared"};
  assert.equal(emulatorCanLaunch(emulator,isDeviceReady(device)),true);
  assert.equal(emulatorCanLaunch({...emulator,availability:"busy"},isDeviceReady({...device,availability:"busy"})),true);
  for(const candidate of [undefined,{...device,connection_status:"worker_offline"},{...device,availability:"needs_review"}])assert.equal(emulatorCanLaunch(emulator,isDeviceReady(candidate)),false);
  for(const state of ["created","running","stopped","preparing","failed","unknown"])assert.equal(emulatorCanLaunch({...emulator,state},isDeviceReady(device)),false);
});
test("missing APKs block application preparation while power controls remain independent",()=>{
  const applications=[{id:"chrome",available:true},{id:"snapchat",available:false}];
  const desired={...emulator,application_ids:["chrome","snapchat"]};
  for(const state of ["created","stopped","unknown","failed"])assert.equal(emulatorCanManage({...desired,state},"start",applications),true);
  for(const state of ["running","ready","unknown","failed"])assert.equal(emulatorCanManage({...desired,state},"stop",applications),true);
  for(const state of ["created","stopped","running","ready","unknown","failed"]){
    assert.equal(emulatorCanManage({...desired,state},"prepare",applications),false);
    assert.equal(emulatorCanManage({...desired,state},"prepare",applications.map(app=>({...app,available:true}))),true);
  }
});
test("desired missing APKs stay configurable but are distinguishable from available applications",()=>{
  const applications=[{id:"chrome",available:true},{id:"instagram",available:false}];
  assert.deepEqual(missingEmulatorApplications(["chrome","instagram","unknown"],applications),["instagram","unknown"]);
  assert.deepEqual(missingEmulatorApplications([],applications),[]);
});
test("uncertain emulator requests retain their exact payload and user-specific retry key",()=>{
  const creation={name:" Téléphone de Zoë ",host_id:"bench-host",application_ids:["chrome","instagram"],idempotency_key:key};
  assert.deepEqual(parseEmulatorCreation(creation),creation);
  assert.deepEqual(parseEmulatorOperation({action:"start",idempotency_key:key}),{action:"start",idempotency_key:key});
  assert.notEqual(emulatorIntentKey("alice","phone"),emulatorIntentKey("bob","phone"));
  assert.notEqual(emulatorIntentKey("alice","phone"),emulatorIntentKey("alice"));
  for(const malformed of [null,{}, {...creation,name:" "},{...creation,application_ids:["chrome","chrome"]},{...creation,application_ids:Array.from({length:13},(_,index)=>`app-${index}`)},{...creation,host_id:"../outside"},{...creation,idempotency_key:"bad"}])assert.equal(parseEmulatorCreation(malformed),null);
  for(const malformed of [null,{}, {action:"delete",idempotency_key:key},{action:"start",idempotency_key:"bad"}])assert.equal(parseEmulatorOperation(malformed),null);
});
