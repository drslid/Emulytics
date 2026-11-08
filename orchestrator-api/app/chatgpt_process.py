"""Bounded official Codex device authorization, isolated from every user's Codex home."""
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4

from .chatgpt_store import MAX_PENDING

MAX_FRAME = 262144


class ProtocolError(Exception):
    pass


def login_response(value):
    if not isinstance(value,dict) or value.get('type')!='chatgptDeviceCode':
        raise ProtocolError()
    code,url,login_id = value.get('userCode'),value.get('verificationUrl'),value.get('loginId')
    if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 -]{0,63}',code):
        raise ProtocolError()
    if not isinstance(login_id,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',login_id):
        raise ProtocolError()
    if url!='https://auth.openai.com/codex/device':
        raise ProtocolError()
    return login_id,code,url


def account_metadata(value):
    account = value.get('account') if isinstance(value,dict) else None
    if not isinstance(account,dict) or account.get('type')!='chatgpt':
        raise ProtocolError()
    email,plan = account.get('email'),account.get('planType')
    if email is not None and (not isinstance(email,str) or len(email)>254 or any(ord(char)<32 for char in email)):
        raise ProtocolError()
    if plan is not None and (not isinstance(plan,str) or not 1<=len(plan)<=64 or not all(char.isalnum() or char=='_' for char in plan)):
        raise ProtocolError()
    return {'email':email,'plan_type':plan}


def read_credentials(private_root):
    descriptor = os.open(Path(private_root)/'auth.json',os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_size>MAX_FRAME:
            raise ProtocolError()
        raw = os.read(descriptor,MAX_FRAME+1)
        if len(raw)>MAX_FRAME:
            raise ProtocolError()
    finally:
        os.close(descriptor)
    try:
        value = json.loads(raw)
    except (ValueError,UnicodeError):
        raise ProtocolError() from None
    tokens = value.get('tokens') if isinstance(value,dict) else None
    if (not isinstance(value,dict) or value.get('auth_mode','chatgpt')!='chatgpt' or value.get('OPENAI_API_KEY')
            or not isinstance(tokens,dict) or any(not isinstance(tokens.get(key),str) or not 1<=len(tokens[key])<=65536
                                                  for key in ('access_token','refresh_token'))):
        raise ProtocolError()
    return value


class ChatGPTManager:
    def __init__(self,binary='/usr/local/bin/codex'):
        self.binary,self.instance = binary,uuid4()
        self.lock,self.jobs = threading.Lock(),{}

    @property
    def available(self):
        return os.getenv('EMULYTIX_CHATGPT_ENABLED','').lower()=='true' and os.path.isfile(self.binary) and os.access(self.binary,os.X_OK)

    def start(self,store,session,attempt):
        with self.lock:
            if not self.available or len(self.jobs)>=MAX_PENDING:
                return False
            stopped = threading.Event()
            thread = threading.Thread(target=self._run,args=(store,session,attempt,stopped),daemon=True,name='chatgpt-device-auth')
            self.jobs[attempt['id']] = (stopped,thread)
            thread.start()
            return True

    def stop(self,attempt_id):
        with self.lock:
            job = self.jobs.get(attempt_id)
            if job:
                job[0].set()
        if job and job[1] is not threading.current_thread():
            job[1].join(timeout=5)

    def close(self):
        with self.lock:
            jobs = list(self.jobs.values())
            for stopped,_ in jobs:
                stopped.set()
        for _,thread in jobs:
            thread.join(timeout=5)

    def _run(self,store,session,attempt,stopped):
        process,completed,error = None,False,'login_interrupted'
        try:
            with tempfile.TemporaryDirectory(prefix='emulytix-chatgpt-') as private_root:
                environment = {'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':private_root,'CODEX_HOME':private_root,'TMPDIR':private_root}
                command = [sys.executable,str(Path(__file__).with_name('adb_child.py')),str(os.getpid()),self.binary,
                           'app-server','--listen','stdio://','-c','cli_auth_credentials_store="file"']
                process = subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                           cwd=private_root,env=environment,start_new_session=True,bufsize=0)
                try:
                    completed = self._protocol(process,private_root,store,session,attempt,stopped)
                finally:
                    # Stop the child before removing its private credential directory.
                    self._terminate(process)
        except ProtocolError:
            error = 'protocol_error'
        except Exception:
            # Provider, subprocess and database exceptions may contain credentials.
            error = 'provider_unavailable'
        finally:
            if process:
                self._terminate(process)
            if not completed:
                try:
                    store.fail(attempt['id'],self.instance,error,expired=stopped.is_set())
                except Exception:
                    pass  # The unrenewed database lease makes status fail closed.
            with self.lock:
                self.jobs.pop(attempt['id'],None)

    @staticmethod
    def _terminate(process):
        if process.poll() is None:
            try:
                os.killpg(process.pid,signal.SIGTERM)
                process.wait(timeout=1)
            except (ProcessLookupError,subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=1)
        for stream in (process.stdin,process.stdout):
            if stream and not stream.closed:
                stream.close()

    def _protocol(self,process,private_root,store,session,attempt,stopped):
        def send(value):
            process.stdin.write((json.dumps(value,separators=(',',':'))+'\n').encode())
            process.stdin.flush()
        send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'emulytix','version':'0.1.0'},'capabilities':{'experimentalApi':False}}})
        stage,server_login_id,buffer,renew = 'initialize',None,b'',0
        deadline = time.monotonic()+600
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ)
            while not stopped.is_set() and time.monotonic()<deadline:
                if time.monotonic()>=renew:
                    if not store.heartbeat(session,attempt['id'],self.instance):
                        return False
                    renew = time.monotonic()+3
                for _,_ in selector.select(timeout=.2):
                    chunk = os.read(process.stdout.fileno(),65536)
                    if not chunk:
                        raise ProtocolError()
                    buffer += chunk
                    if len(buffer)>MAX_FRAME:
                        raise ProtocolError()
                    while b'\n' in buffer:
                        line,buffer = buffer.split(b'\n',1)
                        try:
                            message = json.loads(line)
                        except (ValueError,UnicodeError):
                            raise ProtocolError() from None
                        if not isinstance(message,dict):
                            raise ProtocolError()
                        if message.get('id') in (1,2,3) and 'error' in message:
                            raise ProtocolError()
                        if stage=='initialize' and message.get('id')==1 and isinstance(message.get('result'),dict):
                            send({'method':'initialized','params':{}})
                            send({'id':2,'method':'account/login/start','params':{'type':'chatgptDeviceCode'}})
                            stage = 'login'
                        elif stage=='login' and message.get('id')==2:
                            server_login_id,code,url = login_response(message.get('result'))
                            if not store.pending(session,attempt['id'],self.instance,code,url):
                                return False
                            stage = 'waiting'
                        elif (stage=='waiting' and message.get('method')=='account/login/completed'
                              and isinstance(message.get('params'),dict) and message['params'].get('loginId')==server_login_id):
                            if message['params'].get('success') is not True:
                                raise ProtocolError()
                            send({'id':3,'method':'account/read','params':{'refreshToken':False}})
                            stage = 'account'
                        elif stage=='account' and message.get('id')==3:
                            account = account_metadata(message.get('result'))
                            auth = read_credentials(private_root)
                            return store.complete(session,attempt['id'],self.instance,auth,account)
            return False


_managers,_manager_lock = {},threading.Lock()


def get_manager(store):
    with _manager_lock:
        if store.config.dsn not in _managers:
            _managers[store.config.dsn] = ChatGPTManager()
        return _managers[store.config.dsn]


def close_manager():
    with _manager_lock:
        managers = list(_managers.values())
        _managers.clear()
    for manager in managers:
        manager.close()
