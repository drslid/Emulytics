"""Personal ChatGPT credentials and fenced, bounded device authorizations."""
import json
from uuid import uuid4

from fastapi import HTTPException

from .access import audit_event
from .auth import digest
from .self_security import SelfSecurityStore

PENDING = ('starting','pending')
MAX_PENDING = 8


class ChatGPTStore(SelfSecurityStore):
    @staticmethod
    def _scrub(connection):
        connection.execute("WITH stale AS (SELECT id FROM chatgpt_login_attempts WHERE status IN ('starting','pending') "
            "AND (expires_at<=clock_timestamp() OR lease_expires_at<=clock_timestamp()) ORDER BY expires_at LIMIT 100 FOR UPDATE SKIP LOCKED) "
            "UPDATE chatgpt_login_attempts a SET status=CASE WHEN a.expires_at<=clock_timestamp() THEN 'expired' ELSE 'error' END,"
            "error_code=CASE WHEN a.expires_at<=clock_timestamp() THEN 'login_expired' ELSE 'login_interrupted' END,"
            "user_code=NULL,verification_url=NULL,updated_at=clock_timestamp() FROM stale WHERE a.id=stale.id")

    @staticmethod
    def _view(connection,user_id,available):
        row = connection.execute(
            'SELECT c.*,a.id AS attempt_id,a.status,a.user_code,a.verification_url,a.expires_at,a.error_code,'
            'a.expires_at>clock_timestamp() AS unexpired,a.lease_expires_at>clock_timestamp() AS live '
            'FROM chatgpt_connections c LEFT JOIN chatgpt_login_attempts a ON a.id=c.current_attempt_id WHERE c.user_id=%s',
            (user_id,),
        ).fetchone()
        result = {'provider':'chatgpt','available':available,'status':'disconnected','account':None,'login':None,
                  'connected_at':None,'updated_at':None,'poll_interval_seconds':2,'error_code':None}
        if row is None:
            return result
        result.update(connected_at=row['connected_at'],updated_at=row['updated_at'])
        if row['credentials_ciphertext']:
            result.update(status='connected',account={'email':row['email'],'plan_type':row['plan_type']})
        if row['attempt_id'] and row['status'] in PENDING:
            state,error = row['status'],None
            if not row['unexpired']:
                state,error = 'expired','login_expired'
            elif not row['live']:
                state,error = 'error','login_interrupted'
            result.update(status=state,error_code=error)
            if state=='pending':
                result['login'] = {'id':str(row['attempt_id']),'user_code':row['user_code'],
                    'verification_url':row['verification_url'],'expires_at':row['expires_at']}
        elif row['status'] in ('error','expired'):
            result.update(status=row['status'],error_code=row['error_code'])
        return result

    def status(self,session,available):
        with self.connect() as connection:
            user = self._session_user(connection,session)
            self._scrub(connection)
            return self._view(connection,user['id'],available)

    def begin(self,session,key,runner_id):
        with self.connect() as connection:
            user = self._session_user(connection,session)
            # Serialize the deployment-wide process budget, across API processes too.
            connection.execute('SELECT pg_advisory_xact_lock(783514916)')
            self._scrub(connection)
            previous = connection.execute('SELECT * FROM chatgpt_login_attempts WHERE user_id=%s AND idempotency_key=%s',
                                          (user['id'],key)).fetchone()
            if previous:
                return previous,False
            connection.execute('INSERT INTO chatgpt_connections(user_id) VALUES(%s) ON CONFLICT DO NOTHING',(user['id'],))
            current = connection.execute('SELECT a.id FROM chatgpt_connections c JOIN chatgpt_login_attempts a '
                'ON a.id=c.current_attempt_id WHERE c.user_id=%s AND a.status=ANY(%s) AND a.expires_at>clock_timestamp() '
                'AND a.lease_expires_at>clock_timestamp()',(user['id'],list(PENDING))).fetchone()
            if current:
                raise HTTPException(409,'Une connexion ChatGPT est déjà en cours')
            count = connection.execute('SELECT count(*) AS n FROM chatgpt_login_attempts WHERE status=ANY(%s) '
                'AND expires_at>clock_timestamp() AND lease_expires_at>clock_timestamp()',(list(PENDING),)).fetchone()['n']
            if count>=MAX_PENDING:
                raise HTTPException(429,'Trop de connexions ChatGPT en cours',headers={'Retry-After':'15'})
            attempt = connection.execute("INSERT INTO chatgpt_login_attempts(id,user_id,idempotency_key,runner_id,session_hash,"
                "status,expires_at,lease_expires_at) VALUES(%s,%s,%s,%s,%s,'starting',clock_timestamp()+interval '10 minutes',"
                "clock_timestamp()+interval '15 seconds') RETURNING *",(uuid4(),user['id'],key,runner_id,digest(session))).fetchone()
            connection.execute('UPDATE chatgpt_connections SET current_attempt_id=%s,updated_at=clock_timestamp() WHERE user_id=%s',
                               (attempt['id'],user['id']))
            self._live_session(connection,user)
            audit_event(connection,user['id'],'chatgpt.login.started','chatgpt')
            return attempt,True

    def _owned(self,connection,session,attempt_id,runner_id):
        user = self._session_user(connection,session)
        row = connection.execute('SELECT a.*,a.expires_at>clock_timestamp() AND a.lease_expires_at>clock_timestamp() AS live '
            'FROM chatgpt_connections c JOIN chatgpt_login_attempts a ON a.id=c.current_attempt_id '
            'WHERE c.user_id=%s AND a.id=%s AND a.runner_id=%s AND a.session_hash=%s FOR UPDATE OF c,a',
            (user['id'],attempt_id,runner_id,user['session_hash'])).fetchone()
        return (user,row) if row and row['status'] in PENDING and row['live'] else (user,None)

    def heartbeat(self,session,attempt_id,runner_id):
        with self.connect() as connection:
            user,row = self._owned(connection,session,attempt_id,runner_id)
            if row is None:
                return False
            updated = connection.execute("UPDATE chatgpt_login_attempts SET lease_expires_at=LEAST(expires_at,clock_timestamp()+interval '15 seconds') "
                'WHERE id=%s AND lease_expires_at>clock_timestamp() AND expires_at>clock_timestamp() RETURNING id',(attempt_id,)).fetchone()
            self._live_session(connection,user)
            return updated is not None

    def pending(self,session,attempt_id,runner_id,user_code,url):
        with self.connect() as connection:
            user,row = self._owned(connection,session,attempt_id,runner_id)
            if row is None:
                return False
            connection.execute("UPDATE chatgpt_login_attempts SET status='pending',user_code=%s,verification_url=%s,updated_at=clock_timestamp() WHERE id=%s",
                               (user_code,url,attempt_id))
            connection.execute('UPDATE chatgpt_connections SET updated_at=clock_timestamp() WHERE user_id=%s',(user['id'],))
            self._live_session(connection,user)
            return True

    def complete(self,session,attempt_id,runner_id,auth,account):
        with self.connect() as connection:
            user,row = self._owned(connection,session,attempt_id,runner_id)
            if row is None:
                return False
            encrypted = self.config.cipher.encrypt(json.dumps({'provider':'chatgpt','user_id':str(user['id']),'auth':auth},
                separators=(',',':'),allow_nan=False).encode()).decode()
            connection.execute('UPDATE chatgpt_connections SET credentials_ciphertext=%s,email=%s,plan_type=%s,'
                'connected_at=clock_timestamp(),updated_at=clock_timestamp() WHERE user_id=%s AND current_attempt_id=%s',
                (encrypted,account['email'],account['plan_type'],user['id'],attempt_id))
            connection.execute("UPDATE chatgpt_login_attempts SET status='connected',user_code=NULL,verification_url=NULL,updated_at=clock_timestamp() WHERE id=%s",(attempt_id,))
            self._live_session(connection,user)
            # Do not let encryption or a slow transaction outlive either deadline.
            if not connection.execute('SELECT expires_at>clock_timestamp() AND lease_expires_at>clock_timestamp() AS live '
                                      'FROM chatgpt_login_attempts WHERE id=%s',(attempt_id,)).fetchone()['live']:
                connection.rollback()
                return False
            audit_event(connection,user['id'],'chatgpt.connected','chatgpt')
            return True

    def fail(self,attempt_id,runner_id,code='login_failed',expired=False):
        allowed = {'login_failed','login_expired','login_interrupted','protocol_error','provider_unavailable','login_cancelled'}
        if code not in allowed:
            code = 'login_failed'
        with self.connect() as connection:
            connection.execute("UPDATE chatgpt_login_attempts SET status=CASE WHEN %s OR expires_at<=clock_timestamp() THEN 'expired' ELSE 'error' END,"
                "error_code=CASE WHEN expires_at<=clock_timestamp() THEN 'login_expired' ELSE %s END,user_code=NULL,verification_url=NULL,"
                'updated_at=clock_timestamp() WHERE id=%s AND runner_id=%s AND status=ANY(%s)',
                (expired,code,attempt_id,runner_id,list(PENDING)))

    def cancel(self,session,disconnect=False):
        with self.connect() as connection:
            user = self._session_user(connection,session)
            row = connection.execute('SELECT current_attempt_id FROM chatgpt_connections WHERE user_id=%s FOR UPDATE',(user['id'],)).fetchone()
            attempt_id = row['current_attempt_id'] if row else None
            if attempt_id:
                connection.execute("UPDATE chatgpt_login_attempts SET status='cancelled',user_code=NULL,verification_url=NULL,updated_at=clock_timestamp() "
                                   'WHERE id=%s AND status=ANY(%s)',(attempt_id,list(PENDING)))
            connection.execute('UPDATE chatgpt_connections SET current_attempt_id=NULL,updated_at=clock_timestamp()'+
                (',credentials_ciphertext=NULL,email=NULL,plan_type=NULL,connected_at=NULL' if disconnect else '')+' WHERE user_id=%s',(user['id'],))
            self._live_session(connection,user)
            audit_event(connection,user['id'],'chatgpt.disconnected' if disconnect else 'chatgpt.login.cancelled','chatgpt')
            return attempt_id
