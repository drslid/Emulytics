"""Bounded, persisted activity evidence for the architecture map; no HTTP traffic estimates."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re

from .console_routes import device_connection
from .execution_store import ACTIVE
from .monitor_metrics import STALE_AFTER_SECONDS


WINDOW_SECONDS = 15
SAMPLE_LIMIT = 1000
EVENT_KEYS = ('console_commands','scheduled_runs','executions_started','actions_completed','steps_published','captures_published')


def _recent_events(connection, start, observed_at):
    return connection.execute(
        """WITH audit_recent AS MATERIALIZED (
          SELECT occurred_at AS event_at,
            CASE WHEN action='schedule.dispatched' THEN 'scheduled_runs' ELSE 'console_commands' END AS kind
          FROM audit_log WHERE occurred_at>=%s AND occurred_at<=%s AND (
            (category='automation' AND action='schedule.dispatched') OR
            (category='access' AND action='http.mutation' AND actor_id IS NOT NULL AND
              CASE WHEN jsonb_typeof(metadata->'status_code')='number' THEN
                (metadata->>'status_code')::numeric>=200 AND (metadata->>'status_code')::numeric<300 AND
                (metadata->>'status_code')::numeric=trunc((metadata->>'status_code')::numeric)
              ELSE false END AND
              (entity_id IN ('/runs','/devices') OR entity_id ~ '^/runs/[0-9a-fA-F-]{36}/cancel$' OR
               (entity_id LIKE '/console/%%' AND entity_id !~ '^/console/(account|auth)(/|$)'))))
          ORDER BY occurred_at DESC LIMIT %s
        ), execution_recent AS MATERIALIZED (
          SELECT created_at AS event_at,
            CASE type WHEN 'execution.started' THEN 'executions_started'
              WHEN 'action.done' THEN 'actions_completed' ELSE 'steps_published' END AS kind
          FROM run_events WHERE created_at>=%s AND created_at<=%s
            AND type IN ('execution.started','action.done','execution.step_completed')
          ORDER BY created_at DESC LIMIT %s
        ) SELECT event_at,kind FROM (
          SELECT * FROM audit_recent UNION ALL SELECT * FROM execution_recent
        ) recent ORDER BY event_at DESC,kind LIMIT %s""",
        (start,observed_at,SAMPLE_LIMIT+1,start,observed_at,SAMPLE_LIMIT+1,SAMPLE_LIMIT+1),
    ).fetchall()


def _captures(connection, start, observed_at):
    rows = connection.execute(
        'SELECT evidence FROM executions WHERE updated_at>=%s AND updated_at<=%s '
        'ORDER BY updated_at DESC,id DESC LIMIT %s', (start,observed_at,SAMPLE_LIMIT+1),
    ).fetchall()
    truncated, count, last_at = len(rows)>SAMPLE_LIMIT, 0, None
    for row in rows[:SAMPLE_LIMIT]:
        evidence = row['evidence']
        steps = evidence.get('steps') if isinstance(evidence,dict) else None
        if not isinstance(steps,list):
            continue
        truncated = truncated or len(steps)>14
        seen = set()
        for step in steps[:14]:
            if not isinstance(step,dict):
                continue
            path, digest, captured = step.get('screenshot'), step.get('screenshot_sha256'), step.get('captured_at')
            if (not isinstance(path,str) or len(path)>4096 or not re.fullmatch(r'[a-f0-9]{32}\.png',Path(path).name)
                    or not isinstance(digest,str) or not re.fullmatch(r'[a-fA-F0-9]{64}',digest)
                    or not isinstance(captured,str) or len(captured)>64):
                continue
            try:
                when = datetime.fromisoformat(captured)
                if when.tzinfo is None:
                    continue
                when = when.astimezone(timezone.utc)
            except (ValueError,OverflowError):
                continue
            if not start<=when<=observed_at or path in seen:
                continue
            seen.add(path)
            count += 1
            last_at = max(last_at,when) if last_at else when
    return {'count':count,'last_at':last_at},truncated


def _storage():
    root = os.getenv('EMULYTIX_ARTIFACT_ROOT','')
    if not root:
        return {'status':'unconfigured'}
    descriptor = None
    try:
        descriptor = os.open(root,os.O_RDONLY|os.O_DIRECTORY)
        with os.scandir(descriptor) as entries:
            next(entries,None)
        return {'status':'readable'}
    except (OSError,ValueError):
        return {'status':'unavailable'}
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _confirmed(connection, observed_at, services):
    workers = {(worker['host_id'],worker['instance_id']):worker for worker in services
        if worker['component']=='worker' and worker['status']=='ready' and worker['live']
        and worker['last_seen_at'] is not None
        and observed_at-timedelta(seconds=STALE_AFTER_SECONDS)<worker['last_seen_at']<=observed_at}
    devices = connection.execute(
        'SELECT d.device_id,d.host_id,d.serial,l.owner_id,l.expires_at FROM device_leases l '
        'JOIN devices d USING(device_id) JOIN executions e ON e.id=l.execution_id '
        'AND e.device_id=l.device_id AND e.lease_epoch=l.lease_epoch '
        'WHERE l.owner_id IS NOT NULL AND l.expires_at>%s AND NOT l.quarantined '
        'AND e.status=ANY(%s) AND e.started_at IS NOT NULL AND e.started_at<=%s',
        (observed_at,list(ACTIVE),observed_at),
    ).fetchall()
    confirmed, valid_for = 0, None
    for device in devices:
        owner = workers.get((device['host_id'],device['owner_id']))
        if owner and device_connection(device,[owner])['connection_status']=='connected':
            confirmed += 1
            deadline = min(device['expires_at'],owner['last_seen_at']+timedelta(seconds=STALE_AFTER_SECONDS))
            remaining = (deadline-observed_at).total_seconds()
            valid_for = min(valid_for,remaining) if valid_for is not None else remaining
    return confirmed,valid_for


def topology_snapshot(connection, observed_at, services):
    start = observed_at-timedelta(seconds=WINDOW_SECONDS)
    events = {key:{'count':0,'last_at':None} for key in EVENT_KEYS}
    recent = _recent_events(connection,start,observed_at)
    for row in recent[:SAMPLE_LIMIT]:
        event = events[row['kind']]
        event['count'] += 1
        event['last_at'] = max(event['last_at'],row['event_at']) if event['last_at'] else row['event_at']
    events['captures_published'], captures_truncated = _captures(connection,start,observed_at)
    confirmed,valid_for = _confirmed(connection,observed_at,services)
    return {'window_seconds':WINDOW_SECONDS,'events':events,
        'sampling':{'limit':SAMPLE_LIMIT,'events_truncated':len(recent)>SAMPLE_LIMIT,'captures_truncated':captures_truncated},
        'storage':_storage(),'confirmed_device_executions':confirmed,
        'confirmed_device_executions_valid_for_seconds':valid_for}
