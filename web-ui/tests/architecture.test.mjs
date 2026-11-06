import assert from 'node:assert/strict';
import {test} from 'node:test';
import {buildArchitecture, hasRecentActivity} from '../lib/architecture.ts';
import {topologyIsValid} from '../lib/monitoring.ts';

const observed='2026-11-06T20:00:00Z';
function snapshot(){
  return {
    observed_at:observed, freshness:{stale_after_seconds:20}, web:{status:'ready'}, database:{status:'ready'},
    services:['api','api-go','scheduler','worker'].map(component=>({component,instance_id:component,live:true,status:'ready',age_seconds:1,last_seen_at:observed})),
    queue:{queued:0,active:0}, capacity:{live_workers:1,busy_workers:0,unconfirmed_leases:0},
    fleet:{total:2,connected:1,needs_review:0,worker_offline:0,offline:0,unauthorized:0},
    schedule_health:{overdue:0,errors:0},
    topology:{window_seconds:15,sample_age_seconds:0,confirmed_device_executions:0,confirmed_device_executions_valid_for_seconds:null,storage:{status:'readable'},
      events:Object.fromEntries(['console_commands','scheduled_runs','executions_started','actions_completed','steps_published','captures_published'].map(key=>[key,{count:0,last_at:null}])),
      sampling:{limit:1000,events_truncated:false,captures_truncated:false}}
  };
}
function edge(data,id,live=true,elapsed=0){return buildArchitecture(data,live,elapsed).edges.find(item=>item.id===id);}

test('healthy idle architecture never turns heartbeats or enabled capacity into business traffic',()=>{
  const data=snapshot(), map=buildArchitecture(data,true,0);
  assert.equal(map.nodes.length,8);
  assert.deepEqual(map.edges.filter(item=>item.state==='active').map(item=>item.id),['api-web']);
  assert.equal(edge(data,'web-api-go').state,'ready');
  assert.equal(edge(data,'scheduler-database').state,'ready');
  assert.equal(edge(data,'workers-android').state,'ready');
});
test('current execution animation requires confirmed device work and fresh worker evidence',()=>{
  const data=snapshot();data.queue.active=1;data.capacity.busy_workers=1;
  assert.equal(edge(data,'workers-android').state,'ready','a disconnected busy device cannot borrow an idle connected device');
  data.topology.confirmed_device_executions=1;
  data.topology.confirmed_device_executions_valid_for_seconds=19;
  assert.equal(edge(data,'workers-android').state,'active');
  data.services.find(s=>s.component==='worker').age_seconds=19;
  assert.notEqual(edge(data,'workers-android',true,1).state,'active');
});
test('another healthy worker cannot extend the animation of an expired execution owner',()=>{
  const data=snapshot();Object.assign(data.services.find(s=>s.component==='worker'),{age_seconds:19,active_executions:1});
  data.services.push({component:'worker',instance_id:'another-worker',live:true,status:'ready',age_seconds:0,last_seen_at:observed,active_executions:0});
  data.topology.confirmed_device_executions=1;data.topology.confirmed_device_executions_valid_for_seconds=1;
  assert.equal(edge(data,'workers-android',true,0).state,'active');
  assert.notEqual(edge(data,'workers-android',true,1).state,'active');
  assert.notEqual(buildArchitecture(data,true,1).nodes.find(n=>n.id==='workers').state,'active');
});
test('events animate only their measured links within the short observation window',()=>{
  const data=snapshot();data.topology.events.captures_published={count:2,last_at:'2026-11-06T19:59:50Z'};
  assert.equal(edge(data,'workers-artifacts').state,'active');
  assert.equal(edge(data,'workers-artifacts',true,5).state,'ready');
  assert.equal(edge(data,'web-api').state,'ready');
  data.topology.events.console_commands={count:1,last_at:'2026-11-06T20:00:01Z'};
  assert.equal(hasRecentActivity(data,'console_commands',0),false);
  assert.equal(hasRecentActivity(data,'console_commands',2),false,'future events do not become measured by waiting');
  data.topology.events.console_commands.last_at='broken';assert.equal(hasRecentActivity(data,'console_commands',0),false);
});
test('lost or paused monitoring clears every claimed live state and animation without discarding the graph',()=>{
  const data=snapshot();data.topology.confirmed_device_executions=1;
  data.topology.events.console_commands={count:1,last_at:observed};
  const map=buildArchitecture(data,false,3);
  assert(map.nodes.every(item=>item.state==='unknown'&&!item.confirmed));
  assert(map.edges.every(item=>item.state==='unknown'));
});
test('missing Go and unconfigured storage remain unknown rather than healthy or fabricated outages',()=>{
  const data=snapshot();data.services=data.services.filter(s=>s.component!=='api-go');delete data.topology;
  const map=buildArchitecture(data,true,0);
  assert.equal(map.nodes.find(n=>n.id==='api-go').state,'unknown');
  assert.equal(map.nodes.find(n=>n.id==='artifacts').state,'unknown');
  assert.equal(edge(data,'workers-artifacts').state,'unknown');
});
test('real alerts and sample truncation stay visible while current healthy parts remain usable',()=>{
  const data=snapshot();data.schedule_health.overdue=2;data.topology.sampling.events_truncated=true;
  const map=buildArchitecture(data,true,0);
  assert.equal(map.nodes.find(n=>n.id==='scheduler').state,'warning');
  assert.equal(map.nodes.find(n=>n.id==='scheduler').confirmed,true);
  assert.equal(map.sampled,true);
  data.topology.storage.status='unavailable';assert.equal(edge(data,'workers-artifacts').state,'warning');
});

test('optional legacy telemetry is accepted but malformed activity extensions cannot enter the live view',()=>{
  const data=snapshot();assert.equal(topologyIsValid(data.topology),true);assert.equal(topologyIsValid(undefined),true);
  for(const malformed of [null,{}, {...data.topology,confirmed_device_executions:-1}, {...data.topology,events:{}}, {...data.topology,window_seconds:3600}])assert.equal(topologyIsValid(malformed),false);
  data.topology.events.captures_published={count:Infinity,last_at:observed};assert.equal(topologyIsValid(data.topology),false);
});

test('collection time and SSE cache age cannot extend expired activity or lease evidence',()=>{
  const data=snapshot();data.topology.sample_age_seconds=3;
  data.topology.confirmed_device_executions=1;data.topology.confirmed_device_executions_valid_for_seconds=1;
  assert.notEqual(edge(data,'workers-android').state,'active');
  data.topology.events.captures_published={count:1,last_at:'2026-11-06T19:59:47Z'};
  assert.equal(hasRecentActivity(data,'captures_published',0),false);
});
