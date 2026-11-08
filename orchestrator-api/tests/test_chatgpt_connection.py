from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import time
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.chatgpt_store import ChatGPTStore
from app.chatgpt_process import ChatGPTManager, ProtocolError, login_response, read_credentials
from conftest import CONTROL_TOKEN
from test_authentication import auth_store
from test_user_roles import signed_in


@pytest.fixture
def connection_case(auth_store,app_module):
    user,client,token = signed_in(auth_store,app_module,'builder')
    return ChatGPTStore(auth_store.config),user,client,token


def test_start_is_idempotent_and_get_never_starts_authorization(connection_case):
    store,user,_,token = connection_case
    instance,key = uuid4(),uuid4()
    assert store.status(token,True)['status']=='disconnected'
    attempt,created = store.begin(token,key,instance)
    assert created
    replay,created = store.begin(token,key,instance)
    assert not created and replay['id']==attempt['id']
    assert store.status(token,True)['status']=='starting'


@pytest.mark.parametrize('url',[
    'https://auth.openai.com/other',
    'https://auth.openai.com/codex/device?code=private',
    'https://auth.openai.com:443/codex/device',
    'http://auth.openai.com/codex/device',
    'https://auth.openai.com.attacker.test/codex/device',
])
def test_login_response_rejects_urls_the_console_cannot_display(url):
    with pytest.raises(ProtocolError):
        login_response({'type':'chatgptDeviceCode','loginId':'login-1','userCode':'ABCD-1234','verificationUrl':url})


@pytest.mark.parametrize('code',['<script>','abcd; shell','A\nB','',123])
def test_login_response_rejects_codes_outside_the_display_contract(code):
    with pytest.raises(ProtocolError):
        login_response({'type':'chatgptDeviceCode','loginId':'login-1','userCode':code,
                        'verificationUrl':'https://auth.openai.com/codex/device'})


def test_personal_routes_are_disabled_with_console_authentication(connection_case,monkeypatch):
    _,_,client,_ = connection_case
    monkeypatch.setenv('EMULYTIX_AUTH_ENABLED','false')
    assert client.get('/console/account/chatgpt').status_code==503
    assert client.post('/console/account/chatgpt/cancel',json={}).status_code==503
    assert client.request('DELETE','/console/account/chatgpt',json={}).status_code==503


def test_service_credentials_cannot_read_or_change_a_personal_connection(connection_case):
    _,_,client,_ = connection_case
    client.cookies.clear()
    client.headers['Authorization'] = f'Bearer {CONTROL_TOKEN}'
    assert client.get('/console/account/chatgpt').status_code==401
    assert client.post('/console/account/chatgpt/login',json={'idempotency_key':str(uuid4())}).status_code==401
    assert client.post('/console/account/chatgpt/cancel',json={}).status_code==401
    assert client.request('DELETE','/console/account/chatgpt',json={}).status_code==401


def test_pending_code_and_encrypted_credentials_belong_to_the_current_user(connection_case,auth_store,app_module):
    store,user,_,token = connection_case
    _,_,other = signed_in(auth_store,app_module,'viewer','other-viewer')
    instance = uuid4()
    attempt,_ = store.begin(token,uuid4(),instance)
    assert store.pending(token,attempt['id'],instance,'ABCD-1234','https://auth.openai.com/codex/device')
    assert store.status(other,True)['login'] is None
    auth = {'auth_mode':'chatgpt','tokens':{'access_token':'private-access','refresh_token':'private-refresh'}}
    assert store.complete(token,attempt['id'],instance,auth,{'email':'person@example.test','plan_type':'plus'})
    public = store.status(token,True)
    assert public['status']=='connected' and public['login'] is None
    assert public['account']=={'email':'person@example.test','plan_type':'plus'}
    assert store.status(other,True)['account'] is None
    assert 'private-access' not in json.dumps(public,default=str)
    with store.connect() as connection:
        row = connection.execute('SELECT credentials_ciphertext FROM chatgpt_connections WHERE user_id=%s',(user['id'],)).fetchone()
        assert 'private-access' not in row['credentials_ciphertext']
        decrypted = json.loads(store.config.cipher.decrypt(row['credentials_ciphertext'].encode()))
        assert decrypted['user_id']==str(user['id']) and decrypted['auth']==auth
        assert 'private-access' not in str(connection.execute('SELECT * FROM audit_log').fetchall())


@pytest.mark.parametrize('disconnect',[False,True])
def test_cancel_rejects_a_late_success_without_restoring_credentials(connection_case,disconnect):
    store,_,_,token = connection_case
    instance = uuid4()
    attempt,_ = store.begin(token,uuid4(),instance)
    assert store.cancel(token,disconnect=disconnect)==attempt['id']
    assert not store.complete(token,attempt['id'],instance,{}, {'email':None,'plan_type':None})
    assert store.status(token,True)['status']=='disconnected'
    assert not store.heartbeat(token,attempt['id'],instance)


def test_revoked_session_cannot_renew_or_complete_a_pending_login(connection_case):
    store,_,_,token = connection_case
    instance = uuid4()
    attempt,_ = store.begin(token,uuid4(),instance)
    store.logout(token,None)
    for method,args in [(store.heartbeat,()),(store.complete,({}, {'email':None,'plan_type':None}))]:
        with pytest.raises(HTTPException) as error:
            method(token,attempt['id'],instance,*args)
        assert error.value.status_code==401
    with store.connect() as connection:
        assert connection.execute('SELECT credentials_ciphertext FROM chatgpt_connections').fetchone()['credentials_ciphertext'] is None


@pytest.mark.parametrize('deadline',['expires_at','lease_expires_at'])
def test_expired_or_interrupted_attempts_drop_their_code_and_cannot_succeed(connection_case,deadline):
    store,_,_,token = connection_case
    instance = uuid4()
    attempt,_ = store.begin(token,uuid4(),instance)
    assert store.pending(token,attempt['id'],instance,'ABCD-1234','https://auth.openai.com/codex/device')
    with store.connect() as connection:
        connection.execute(f"UPDATE chatgpt_login_attempts SET {deadline}=clock_timestamp()-interval '1 second' WHERE id=%s",(attempt['id'],))
    result = store.status(token,True)
    assert result['status']==('expired' if deadline=='expires_at' else 'error')
    assert result['login'] is None
    assert not store.complete(token,attempt['id'],instance,{}, {'email':None,'plan_type':None})
    with store.connect() as connection:
        assert connection.execute('SELECT user_code FROM chatgpt_login_attempts WHERE id=%s',(attempt['id'],)).fetchone()['user_code'] is None


def test_simultaneous_retries_create_only_one_attempt(connection_case):
    store,_,_,token = connection_case
    key,instance = uuid4(),uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:store.begin(token,key,instance),range(2)))
    assert sorted(created for _,created in results)==[False,True]
    assert results[0][0]['id']==results[1][0]['id']


@pytest.mark.parametrize('complete',[True,False])
def test_official_protocol_lifecycle_is_isolated_and_cleans_private_files(connection_case,tmp_path,monkeypatch,complete):
    store,_,_,token = connection_case
    binary,proof = tmp_path/'fake-codex',tmp_path/'proof.json'
    binary.write_text(f'''#!{sys.executable}
import json,os,sys
from pathlib import Path
root=Path(os.environ['CODEX_HOME'])
assert root==Path.cwd()==Path(os.environ['HOME'])
assert root.stat().st_mode & 0o077 == 0
Path({str(proof)!r}).write_text(json.dumps({{'root':str(root),'inherited_secret':'OPENAI_API_KEY' in os.environ}}))
def send(value):
    print(json.dumps(value),flush=True)
for line in sys.stdin:
    message=json.loads(line)
    if message['method']=='initialize':
        send({{'id':message['id'],'result':{{}}}})
    elif message['method']=='account/login/start':
        assert message['params']=={{'type':'chatgptDeviceCode'}}
        send({{'id':message['id'],'result':{{'type':'chatgptDeviceCode','loginId':'test-login','userCode':'ABCD-1234','verificationUrl':'https://auth.openai.com/codex/device'}}}})
        if {complete!r}:
            send({{'method':'account/login/completed','params':{{'loginId':'test-login','success':True}}}})
    elif message['method']=='account/read':
        (root/'auth.json').write_text(json.dumps({{'auth_mode':'chatgpt','tokens':{{'access_token':'fixture-access','refresh_token':'fixture-refresh'}}}}))
        send({{'id':message['id'],'result':{{'account':{{'type':'chatgpt','email':'fixture@example.test','planType':'plus'}}}}}})
    else:
        assert message['method']=='initialized'
''')
    binary.chmod(0o700)
    monkeypatch.setenv('EMULYTIX_CHATGPT_ENABLED','true')
    monkeypatch.setenv('OPENAI_API_KEY','must-not-reach-the-child')
    manager = ChatGPTManager(str(binary))
    attempt,_ = store.begin(token,uuid4(),manager.instance)
    assert manager.start(store,token,attempt)
    try:
        deadline = time.monotonic()+8
        while time.monotonic()<deadline:
            status = store.status(token,True)
            if status['status']==('connected' if complete else 'pending'):
                break
            time.sleep(.05)
        assert status['status']==('connected' if complete else 'pending')
        if not complete:
            assert store.cancel(token)==attempt['id']
            manager.stop(attempt['id'])
            assert store.status(token,True)['status']=='disconnected'
    finally:
        manager.close()
    assert not manager.jobs
    observed = json.loads(proof.read_text())
    assert observed['inherited_secret'] is False
    assert not Path(observed['root']).exists()


def test_credential_cache_rejects_symlinks_and_non_chatgpt_accounts(tmp_path):
    target = tmp_path/'other.json'
    target.write_text('{"OPENAI_API_KEY":"fixture-key"}')
    (tmp_path/'auth.json').symlink_to(target)
    with pytest.raises(OSError):
        read_credentials(tmp_path)
    (tmp_path/'auth.json').unlink()
    (tmp_path/'auth.json').write_text(target.read_text())
    with pytest.raises(ProtocolError):
        read_credentials(tmp_path)
