import assert from "node:assert/strict";
import { test } from "node:test";
import { dayTotal, parseDashboardCapacity, parseDashboardSnapshot, percentOf, summarizeDays } from "../lib/dashboard.ts";

function snapshot() {
  const days = Array.from({length:7},(_,index)=>({date:`2026-11-${String(index+1).padStart(2,"0")}`,succeeded:index===6?5:0,failed:index===5?2:0,cancelled:0,needs_review:index===0?1:0}));
  return {observed_at:"2026-11-07T12:00:00Z",timezone:"Europe/Paris",window_start:"2026-10-31T23:00:00Z",window_end:"2026-11-07T12:00:00Z",days,totals:summarizeDays(days)};
}

test("daily totals include every terminal outcome and retain real zero days",()=>{
  const result=snapshot();
  assert.deepEqual(result.totals,{succeeded:5,failed:2,cancelled:0,needs_review:1,finished:8});
  assert.equal(dayTotal(result.days[1]),0);
  assert.deepEqual(parseDashboardSnapshot(result),result);
  const empty={...result,days:result.days.map(day=>({...day,succeeded:0,failed:0,needs_review:0}))};
  empty.totals=summarizeDays(empty.days);
  assert.equal(parseDashboardSnapshot(empty).totals.finished,0);
});

test("missing, duplicated or inconsistent aggregate days never become invented chart data",()=>{
  for(const change of [data=>data.days.pop(),data=>data.days[1].date=data.days[0].date,data=>data.days[0].date="2026-02-30",data=>data.days[0].failed=-1,data=>data.days[0].failed=null,data=>data.totals.finished++,data=>data.timezone="invalid/timezone",data=>data.observed_at="invalid"]){
    const data=snapshot();change(data);assert.throws(()=>parseDashboardSnapshot(data));
  }
});

test("chart ratios distinguish measured zero from absent or invalid denominators",()=>{
  assert.equal(percentOf(0,5),0);assert.equal(percentOf(3,4),75);assert.equal(percentOf(1,1),100);
  for(const [part,total] of [[0,0],[null,2],[2,null],[3,2],[-1,2],[NaN,2],[1,Infinity]])assert.equal(percentOf(part,total),null);
});

test("worker slots and connected or ready phones keep their distinct denominators",()=>{
  const data={observed_at:"2026-11-07T12:00:00Z",capacity:{live_workers:2,busy_workers:1,idle_workers:1},fleet:{total:10,connected:8,ready:6}};
  assert.deepEqual(parseDashboardCapacity(data),{observed_at:data.observed_at,workers:{total:2,busy:1,idle:1},devices:{total:10,connected:8,ready:6},unconfirmedDevices:null});
  assert.equal(percentOf(1,2),50);assert.equal(percentOf(6,10),60);
  assert.deepEqual(parseDashboardCapacity({...data,capacity:{live_workers:0,busy_workers:0,idle_workers:0}}).workers,{total:0,busy:0,idle:0});
  assert.equal(parseDashboardCapacity({...data,capacity:{live_workers:2,busy_workers:3,idle_workers:0}}).workers,null);
  assert.equal(parseDashboardCapacity({...data,fleet:{total:10,connected:null,ready:0}}).devices,null);
  assert.equal(parseDashboardCapacity({observed_at:data.observed_at}).workers,null);
});

test("unverified Android connections are reported independently of confirmed zero connections",()=>{
  const input={observed_at:"2026-11-07T12:00:00Z",fleet:{total:2,connected:0,ready:0,unknown:1}};
  const result=parseDashboardCapacity(input);
  assert.equal(result.devices.connected,0);
  assert.equal(result.unconfirmedDevices,1);
  assert.equal(parseDashboardCapacity({...input,fleet:{...input.fleet,unknown:0}}).unconfirmedDevices,0);
  assert.equal(parseDashboardCapacity({...input,fleet:{...input.fleet,unknown:3}}).unconfirmedDevices,null);
});
