"""Managed Android configuration; all runtime effects use the existing run queue."""
from uuid import UUID, uuid4
import hashlib
import re

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .access import audit_event, permissions_for
from .console_routes import device_connection
from .execution_store import ACTIVE, ExecutionStore
from .run_models import RunSubmission, WorkflowRegistration
from .run_store import RunStore, fingerprint


PRESETS = {
    'chrome': ('Google Chrome','com.android.chrome','system'),
    'snapchat': ('Snapchat','com.snapchat.android','apk'),
    'linkedin': ('LinkedIn','com.linkedin.android','apk'),
    'instagram': ('Instagram','com.instagram.android','apk'),
    'tiktok': ('TikTok','com.zhiliaoapp.musically','apk'),
}
STATES = {'created','starting','running','ready','stopped','preparing','failed','unknown'}


def _key(actor_id, key):
    return 'emulator-' + hashlib.sha256((str(actor_id or 'service')+'\0'+key).encode()).hexdigest()


class EmulatorStore(RunStore):
    @staticmethod
    def _hosts(connection):
        return [row['host_id'] for row in connection.execute(
            "SELECT DISTINCT host_id FROM service_heartbeats WHERE component='worker' AND status='ready' "
            "AND last_seen_at>clock_timestamp()-interval '20 seconds' AND host_id IS NOT NULL AND host_id<>'' "
            "AND metrics->'managed_emulators'='true'::jsonb ORDER BY host_id",
        ).fetchall()]

    @staticmethod
    def _actor(connection, actor_id):
        if actor_id is None:
            return
        actor = connection.execute(
            'SELECT active,totp_enabled,password_change_required,role FROM auth_users WHERE id=%s FOR SHARE', (actor_id,),
        ).fetchone()
        if not actor or not actor['active'] or not actor['totp_enabled'] or actor['password_change_required'] or 'devices.write' not in permissions_for(actor['role']):
            raise HTTPException(403, 'Device administration permission required')

    @staticmethod
    def _catalog(connection):
        uploaded = connection.execute('SELECT * FROM applications ORDER BY created_at DESC,id DESC').fetchall()
        applications = []
        for app_id, (name, package, source) in PRESETS.items():
            artifact = next((row for row in uploaded if row['package_name']==package), None) if source=='apk' else None
            applications.append({'id':app_id,'name':name,'package_name':package,'source':source,
                'filename':artifact['filename'] if artifact else None,'sha256':artifact['sha256'] if artifact else None,
                'size_bytes':artifact['size_bytes'] if artifact else 0,'available':source=='system' or artifact is not None})
        preset_packages = {value[1] for value in PRESETS.values() if value[2]=='apk'}
        applications.extend({**row,'id':str(row['id']),'source':'apk','available':True} for row in uploaded if row['package_name'] not in preset_packages)
        return applications, uploaded

    @classmethod
    def _resolve(cls, connection, ids, *, required=False):
        catalog, uploaded = cls._catalog(connection)
        lookup = {row['id']:row for row in catalog}
        lookup.update({str(row['id']):{**row,'id':str(row['id']),'source':'apk','available':True} for row in uploaded})
        resolved, packages = [], set()
        for app_id in ids:
            row = lookup.get(app_id)
            if row is None:
                raise HTTPException(422, 'Unknown application')
            if required and not row['available']:
                raise HTTPException(422, 'Upload an APK for each selected application before preparing the emulator')
            if row['package_name'] in packages:
                raise HTTPException(422, 'Select each Android package once')
            packages.add(row['package_name'])
            resolved.append({key:row[key] for key in ('id','name','package_name','source','filename','sha256','size_bytes')})
        return resolved

    @staticmethod
    def _workers(connection):
        return connection.execute(
            "SELECT host_id,status,metrics,last_seen_at,last_seen_at>clock_timestamp()-interval '20 seconds' AS live "
            "FROM service_heartbeats WHERE component='worker' ORDER BY last_seen_at DESC",
        ).fetchall()

    @classmethod
    def _record(cls, connection, device_id, workers=None):
        record = connection.execute(
            "SELECT m.id,m.device_id,d.display_name,d.host_id,d.serial,m.slot,m.application_ids,m.installed_packages,"
            'd.kind AS device_kind,d.status AS device_status,d.created_at AS device_created_at,'
            'active_execution.run_id AS active_run_id,l.expires_at AS lease_expires_at,'
            "CASE WHEN r.status IN ('failed','needs_review') THEN 'failed' "
            "WHEN r.status='cancelled' AND m.state IN ('starting','preparing') THEN 'unknown' ELSE m.state END AS state,"
            'COALESCE(m.last_error,(SELECT error FROM executions WHERE run_id=m.last_run_id AND device_id=m.device_id ORDER BY attempt DESC LIMIT 1)) AS last_error,'
            'm.last_run_id,r.status AS operation_status,m.updated_at,'
            "CASE WHEN l.quarantined OR (l.owner_id IS NOT NULL AND l.expires_at<=clock_timestamp()) THEN 'needs_review' "
            "WHEN l.owner_id IS NOT NULL THEN 'busy' ELSE 'declared' END AS availability "
            'FROM managed_emulators m JOIN devices d USING(device_id) '
            'LEFT JOIN runs r ON r.id=m.last_run_id LEFT JOIN device_leases l USING(device_id) '
            'LEFT JOIN executions active_execution ON active_execution.id=l.execution_id WHERE m.device_id=%s', (device_id,),
        ).fetchone()
        if record is None:
            return None
        device = {key:record[key] for key in ('device_id','display_name','host_id','serial','availability')}
        device.update(kind=record.pop('device_kind'),status=record.pop('device_status'),
                      created_at=record.pop('device_created_at'),active_run_id=record.pop('active_run_id'),
                      lease_expires_at=record.pop('lease_expires_at'))
        device.update(device_connection(device,cls._workers(connection) if workers is None else workers))
        return {**record,'device':device}

    @classmethod
    def _lock_device(cls, connection, device_id):
        device = connection.execute('SELECT device_id FROM devices WHERE device_id=%s FOR UPDATE', (device_id,)).fetchone()
        if device is None or not connection.execute('SELECT id FROM managed_emulators WHERE device_id=%s FOR UPDATE', (device_id,)).fetchone():
            raise HTTPException(404, 'Managed emulator not found')

    @staticmethod
    def _idle(connection, device_id):
        if connection.execute('SELECT 1 FROM executions WHERE device_id=%s AND status=ANY(%s) LIMIT 1', (device_id,['queued',*ACTIVE])).fetchone():
            raise HTTPException(409, 'The device already has queued or active work')
        lease = connection.execute('SELECT owner_id,quarantined FROM device_leases WHERE device_id=%s', (device_id,)).fetchone()
        if lease and (lease['owner_id'] is not None or lease['quarantined']):
            raise HTTPException(409, 'The device lease must be free and confirmed')

    def list_emulators(self):
        with self.connect() as connection:
            ids = connection.execute('SELECT device_id FROM managed_emulators ORDER BY updated_at DESC,device_id').fetchall()
            catalog, _ = self._catalog(connection)
            hosts = self._hosts(connection)
            workers = self._workers(connection)
            return {'items':[self._record(connection,row['device_id'],workers) for row in ids],
                'applications':[{key:row[key] for key in ('id','name','package_name','source','size_bytes','available')} for row in catalog],
                'hosts':hosts,'enabled':bool(hosts),'max_per_host':4}

    def create_emulator(self, name, host_id, application_ids, idempotency_key, actor_id=None):
        key = _key(actor_id,idempotency_key)
        digest = fingerprint({'name':name,'host_id':host_id,'application_ids':application_ids})
        with self.connect() as connection:
            self._actor(connection,actor_id)
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('emulator-create:'+key,))
            previous = connection.execute('SELECT device_id,create_hash FROM managed_emulators WHERE create_key=%s',(key,)).fetchone()
            if previous:
                if previous['create_hash']!=digest:
                    raise HTTPException(409,'Creation key already used with different content')
                return self._record(connection,previous['device_id']),False
            self._resolve(connection,application_ids)
            connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('emulator-host:'+host_id,))
            if host_id not in self._hosts(connection):
                raise HTTPException(409,'No active worker can manage emulators on this host')
            slots = {row['slot'] for row in connection.execute('SELECT slot FROM managed_emulators WHERE host_id=%s',(host_id,)).fetchall()}
            serials = {row['serial'] for row in connection.execute('SELECT serial FROM devices WHERE host_id=%s',(host_id,)).fetchall()}
            slot = next((slot for slot in range(1,5) if slot not in slots and f'emulator-{5554+slot*2}' not in serials),None)
            if slot is None:
                raise HTTPException(409,'No managed emulator slot is available on this host')
            emulator_id = uuid4()
            device_id = 'emu-'+emulator_id.hex[:12]
            inserted = connection.execute('INSERT INTO devices(device_id,display_name,host_id,serial,kind) VALUES(%s,%s,%s,%s,\'emulator\') ON CONFLICT DO NOTHING RETURNING device_id',
                (device_id,name,host_id,f'emulator-{5554+slot*2}')).fetchone()
            if inserted is None:
                raise HTTPException(409,'The device slot changed; retry creation')
            connection.execute('INSERT INTO managed_emulators(id,device_id,host_id,slot,application_ids,create_key,create_hash,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                (emulator_id,device_id,host_id,slot,Jsonb(application_ids),key,digest,actor_id))
            audit_event(connection,actor_id,'emulator.created',device_id,category='automation')
            return self._record(connection,device_id),True

    def configure(self, device_id, application_ids, actor_id=None):
        with self.connect() as connection:
            self._actor(connection,actor_id)
            self._lock_device(connection,device_id)
            self._idle(connection,device_id)
            self._resolve(connection,application_ids)
            connection.execute("UPDATE managed_emulators SET application_ids=%s,state=CASE WHEN application_ids=%s THEN state WHEN state IN ('created','stopped','running') THEN state WHEN state='ready' THEN 'running' ELSE 'unknown' END,last_error=NULL,updated_at=clock_timestamp() WHERE device_id=%s",
                (Jsonb(application_ids),Jsonb(application_ids),device_id))
            audit_event(connection,actor_id,'emulator.configured',device_id,category='automation')
            return self._record(connection,device_id)

    def queue_operation(self, device_id, action, idempotency_key, actor_id=None):
        if action not in {'start','prepare','stop'}:
            raise HTTPException(422,'Invalid emulator action')
        key = _key(actor_id,idempotency_key)
        with self.connect() as connection:
            self._actor(connection,actor_id)
            self._lock_device(connection,device_id)
            previous = connection.execute('SELECT r.id,o.device_id,o.action FROM runs r LEFT JOIN emulator_operations o ON o.run_id=r.id WHERE r.idempotency_key=%s',(key,)).fetchone()
            if previous:
                if previous['device_id']!=device_id or previous['action']!=action:
                    raise HTTPException(409,'Operation key already used with different content')
                return {'run_id':previous['id'],'emulator':self._record(connection,device_id)}
            self._idle(connection,device_id)
            emulator = self._record(connection,device_id)
            if emulator['host_id'] not in self._hosts(connection):
                raise HTTPException(409,'The emulator management worker is unavailable')
            applications = self._resolve(connection,emulator['application_ids'],required=action=='prepare') if action!='stop' else []
            # Separate power-only starts from already published start-and-prepare definitions.
            suffix = fingerprint({'mode':'power-only','applications':applications} if action=='start' else applications)[:12]
            workflow_id = f'emulator-system-{action}-{emulator["id"].hex[:12]}-{suffix}'
            steps = [{'id':'runtime','action':'screenshot','args':{},'assert':{'type':'package_installed','value':'com.android.chrome'}}]
            if action=='prepare':
                steps += [{'id':f'app-{index+1}','action':'screenshot','args':{},'assert':{'type':'package_installed','value':'com.android.chrome'}} for index,_ in enumerate(applications)]
            workflow = WorkflowRegistration.model_validate({'workflow_id':workflow_id,'version':1,'steps':steps})
            self._register_workflow(connection,workflow,internal=True)
            connection.execute('INSERT INTO automation_publications(workflow_id,version,name,instructions) VALUES(%s,1,%s,%s) ON CONFLICT DO NOTHING',
                (workflow_id,{'start':'Démarrage','prepare':'Préparation','stop':'Arrêt'}[action]+' · '+emulator['display_name'],'Managed emulator operation'))
            submission = RunSubmission.model_validate({'workflow_id':workflow_id,'workflow_version':1,'device_ids':[device_id],'max_concurrency':1,'parameters':{},'idempotency_key':key})
            run = self._submit_run(connection,submission,internal=True)
            connection.execute('INSERT INTO emulator_operations(run_id,device_id,action,applications,created_by,service_actor) VALUES(%s,%s,%s,%s,%s,%s)',
                (run['id'],device_id,action,Jsonb(applications),actor_id,actor_id is None))
            connection.execute('UPDATE managed_emulators SET last_run_id=%s,last_error=NULL,updated_at=clock_timestamp() WHERE device_id=%s',(run['id'],device_id))
            audit_event(connection,actor_id,'emulator.operation.queued',device_id,{'run_id':str(run['id'])},category='automation')
            return {'run_id':run['id'],'emulator':self._record(connection,device_id)}

    def add_application(self, metadata, actor_id=None):
        try:
            app_id = UUID(str(metadata['id']))
            if metadata['filename']!=str(app_id)+'.apk' or not re.fullmatch(r'[a-f0-9]{64}',metadata['sha256']) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]{1,199}',metadata['package_name']):
                raise ValueError()
            if type(metadata['size_bytes']) is not int or not 1<=metadata['size_bytes']<=134217728 or not isinstance(metadata['name'],str) or not 1<=len(metadata['name'])<=160:
                raise ValueError()
        except (KeyError,TypeError,ValueError):
            raise HTTPException(422,'Invalid application metadata') from None
        with self.connect() as connection:
            self._actor(connection,actor_id)
            connection.execute('INSERT INTO applications(id,filename,sha256,package_name,name,size_bytes,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                (app_id,metadata['filename'],metadata['sha256'],metadata['package_name'],metadata['name'],metadata['size_bytes'],actor_id))
            audit_event(connection,actor_id,'application.uploaded',str(app_id),category='automation')
            return {'id':str(app_id),'name':metadata['name'],'package_name':metadata['package_name'],'source':'apk','size_bytes':metadata['size_bytes'],'available':True}

    def managed_device(self, device_id):
        with self.connect() as connection:
            return self._record(connection,device_id)

    def list_managed(self, host_id):
        with self.connect() as connection:
            workers = self._workers(connection)
            return [self._record(connection,row['device_id'],workers) for row in connection.execute('SELECT device_id FROM managed_emulators WHERE host_id=%s ORDER BY slot',(host_id,)).fetchall()]

    def operation(self, execution_id):
        with self.connect() as connection:
            row = connection.execute('SELECT m.id,m.device_id,d.host_id,d.serial,m.slot,o.action,o.applications,o.service_actor,u.active,u.totp_enabled,u.password_change_required,u.role FROM executions e JOIN emulator_operations o ON o.run_id=e.run_id AND o.device_id=e.device_id JOIN managed_emulators m ON m.device_id=o.device_id JOIN devices d ON d.device_id=m.device_id LEFT JOIN auth_users u ON u.id=o.created_by WHERE e.id=%s',(execution_id,)).fetchone()
            if row is None:
                return None
            authorized = row['service_actor'] or bool(row['active'] and row['totp_enabled'] and not row['password_change_required'] and 'devices.write' in permissions_for(row['role']))
            return {**{key:row[key] for key in ('id','device_id','host_id','serial','slot','action','applications')},'authorized':authorized}

    def update_runtime(self, device_id, state, installed_packages=None, last_error=None, *, execution_id, owner_id, lease_epoch):
        if state not in STATES:
            raise ValueError('Invalid emulator state')
        with self.connect() as connection:
            locked = ExecutionStore._lock(connection,execution_id)
            if not ExecutionStore._owns(locked,owner_id,lease_epoch) or locked[0]['device_id']!=device_id:
                return False
            updated = connection.execute('UPDATE managed_emulators m SET state=%s,installed_packages=COALESCE(%s::jsonb,installed_packages),last_error=%s,updated_at=clock_timestamp() WHERE device_id=%s AND EXISTS(SELECT 1 FROM device_leases l JOIN executions e ON e.id=l.execution_id WHERE l.device_id=m.device_id AND e.device_id=m.device_id AND e.id=%s AND l.owner_id=%s AND l.lease_epoch=%s AND l.expires_at>clock_timestamp() AND NOT l.quarantined AND e.status=ANY(%s)) RETURNING m.id',
                (state,Jsonb(installed_packages) if installed_packages is not None else None,last_error[:512] if last_error else None,device_id,execution_id,owner_id,lease_epoch,list(ACTIVE))).fetchone()
            if not ExecutionStore._before_deadline(connection,locked[2]['expires_at']):
                connection.rollback()
                return False
            return updated is not None
