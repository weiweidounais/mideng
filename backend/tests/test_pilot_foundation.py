"""Foundation contracts against real SQLite/HTTP, including independent identities."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func, inspect, text
from sqlalchemy.exc import IntegrityError
from app.pilot import make_app
from app.pilot_models import Account, Session, Project, Membership, Audit, Outbox, Todo, Idempotency
from app.pilot_policy import read_policy
from app.pilot_service import Store, uid, hasher

PASS = 'test-password'


def mutation(client, method, path, body, key=None):
    session = client.get('/api/session').json()
    return client.request(method, '/api'+path, json=body,
        headers={'X-CSRF-Token': session.get('csrf',''), 'X-Idempotency-Key': key or uid()})


def login(client, username='admin'):
    r = client.post('/api/auth/login', json={'username': username, 'password': PASS})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def env(tmp_path):
    app = make_app(f'sqlite:///{tmp_path / "pilot.db"}', worker=False)
    with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 50123)) as admin:
        r = admin.post('/api/setup', json={'username':'admin','display_name':'测试管理员','password':PASS})
        assert r.status_code == 200, r.text
        yield app, admin


def add_account(admin, name='alice'):
    r=mutation(admin,'POST','/accounts',{'username':name,'display_name':name,'password':PASS})
    assert r.status_code==200,r.text
    return r.json()


def add_project(admin, code='P1'):
    r=mutation(admin,'POST','/projects',{'code':code,'name':'脱敏测试项目'})
    assert r.status_code==200,r.text
    return r.json()


def grant(admin, p, a, roles=None, **kw):
    body={'account_id':a['id'],'roles':roles or ['市场'],'revision':0,**kw}
    return mutation(admin,'PUT',f"/projects/{p['id']}/members",body)


def user_client(app, username):
    c=TestClient(app, base_url='http://127.0.0.1',client=('127.0.0.1',50124))
    login(c,username)
    return c


def test_setup_closes_and_session_cookie_is_httponly(env):
    _,admin=env
    assert admin.get('/api/setup').json()=={'required':False}
    assert admin.post('/api/setup',json={'username':'root','display_name':'R','password':PASS}).status_code==409
    r=admin.post('/api/auth/login',json={'username':'admin','password':PASS})
    assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']
    assert 'password' not in r.text


def test_setup_requires_real_loopback(tmp_path):
    app=make_app(f'sqlite:///{tmp_path / "remote.db"}',worker=False)
    with TestClient(app,base_url='http://127.0.0.1',client=('192.0.2.2',50000)) as c:
        assert c.post('/api/setup',json={'username':'aa','display_name':'A','password':PASS}).status_code==403


def test_anonymous_csrf_origin_and_spoofed_identity_rejected(env):
    app,admin=env
    with TestClient(app,base_url='http://127.0.0.1') as c:
        assert c.get('/api/projects').status_code==401
    assert admin.post('/api/projects',json={'code':'P1','name':'A'}).status_code==403
    assert admin.post('/api/auth/login',json={'username':'admin','password':PASS},headers={'Origin':'https://evil.invalid'}).status_code==403
    r=mutation(admin,'POST','/projects',{'code':'P1','name':'A','actor_id':'forged'})
    assert r.status_code==422 and 'forged' not in r.text
    assert r.json()['error']['request_id']


def test_independent_account_cannot_create_accounts_or_projects(env):
    app,admin=env;add_account(admin);alice=user_client(app,'alice')
    assert alice.get('/api/accounts').status_code==403
    assert mutation(alice,'POST','/projects',{'code':'x','name':'X'}).status_code==403
    assert alice.get('/api/projects').json()==[]
    alice.close()


def test_project_scoping_guessed_ids_members_audit_and_todos(env):
    app,admin=env;a=add_account(admin);p=add_project(admin);other=add_project(admin,'P2')
    assert grant(admin,p,a).status_code==200
    alice=user_client(app,'alice')
    assert [x['id'] for x in alice.get('/api/projects').json()]==[p['id']]
    for suffix in ['', '/members','/audit']:
        assert alice.get('/api/projects/'+other['id']+suffix).status_code==404
    assert alice.get('/api/projects/'+p['id']+'/audit').status_code==403
    app.state.store.drain()
    assert {t['project_id'] for t in alice.get('/api/todos').json()}=={p['id']}
    alice.close()


def test_technical_admin_without_membership_cannot_read_business(env):
    _,admin=env;p=add_project(admin);aid=admin.get('/api/session').json()['account']['id']
    assert grant(admin,p,{'id':aid},['管理员'],revision=1,active=False).status_code==200
    assert admin.get('/api/projects/'+p['id']).status_code==404
    assert admin.get('/api/projects').json()==[]
    # Administration may restore membership, never implicitly sign a business decision.
    assert grant(admin,p,{'id':aid},['管理员'],revision=2).status_code==200
    view=admin.get('/api/projects/'+p['id']).json()
    assert 'cost.publish' not in view['actions'] and 'quality.release' not in view['actions']


@pytest.mark.parametrize('roles,action,expected',[(['市场'],'project.edit',False),(['项目经理'],'project.edit',True),(['管理员'],'cost.publish',False),(['财务'],'cost.publish',True),(['工厂'],'quality.release',False),(['质量'],'quality.release',True)])
def test_roles_are_server_derived(env,roles,action,expected):
    app,admin=env;a=add_account(admin);p=add_project(admin);assert grant(admin,p,a,roles).status_code==200
    alice=user_client(app,'alice');view=alice.get('/api/projects/'+p['id']).json()
    assert (action in view['actions']) is expected
    result=mutation(alice,'PATCH','/projects/'+p['id'],{'name':'试改','revision':1})
    assert result.status_code==(200 if 'project.edit' in view['actions'] else 403)
    alice.close()


def test_member_revoke_hides_project_todos_and_cached_request_results(env):
    app,admin=env;a=add_account(admin);p=add_project(admin);grant(admin,p,a,['项目经理']);alice=user_client(app,'alice')
    key=uid();r=mutation(alice,'PATCH','/projects/'+p['id'],{'name':'修改','revision':1},key)
    assert r.status_code==200
    assert alice.get('/api/requests/'+key).status_code==200
    app.state.store.drain()
    assert alice.get('/api/todos').json()
    assert grant(admin,p,a,['项目经理'],revision=1,active=False).status_code==200
    assert alice.get('/api/projects/'+p['id']).status_code==404
    assert alice.get('/api/todos').json()==[]
    assert alice.get('/api/requests/'+key).status_code==404
    assert mutation(alice,'PATCH','/projects/'+p['id'],{'name':'修改','revision':1},key).status_code==404
    alice.close()


def test_member_time_window_and_unknown_accounts(env):
    app,admin=env;a=add_account(admin);p=add_project(admin)
    future=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
    assert grant(admin,p,a,valid_from=future).status_code==200
    alice=user_client(app,'alice');assert alice.get('/api/projects').json()==[]
    assert grant(admin,p,a,revision=1,valid_from='2020-01-01T00:00:00Z',valid_until='2021-01-01T00:00:00Z').status_code==200
    assert alice.get('/api/projects').json()==[]
    assert grant(admin,p,{'id':'unknown'}).status_code==422
    assert grant(admin,p,a,revision=2,roles=['伪造岗位']).status_code==422
    assert grant(admin,p,a,revision=2,valid_from='2026-01-01T00:00:00').status_code==422
    alice.close()


def test_project_idempotency_returns_original_and_conflicts_on_changed_payload(env):
    app,admin=env;key=uid();body={'code':'P1','name':'第一版'}
    one=mutation(admin,'POST','/projects',body,key);two=mutation(admin,'POST','/projects',body,key)
    assert one.json()==two.json()
    assert mutation(admin,'POST','/projects',body|{'name':'变化'},key).status_code==409
    assert admin.get('/api/requests/'+key).json()['result']==one.json()
    with app.state.store.transaction() as db:
        assert db.scalar(select(func.count()).select_from(Project))==1
        assert db.scalar(select(func.count()).select_from(Outbox))==1
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='project.create'))==1


def test_concurrent_revision_has_one_winner_and_retry_is_idempotent(env):
    app,admin=env;p=add_project(admin);body={'name':'并发甲','revision':1};key=uid()
    cookie=dict(admin.cookies);csrf=admin.get('/api/session').json()['csrf']
    def write(name):
        # Outer fixture owns ASGI lifespan; parallel clients model concurrent HTTP,
        # not concurrent migration/startup of the same single-process application.
        c=TestClient(app,base_url='http://127.0.0.1')
        try:
            c.cookies.update(cookie)
            return c.patch('/api/projects/'+p['id'],json={'name':name,'revision':1},headers={'X-CSRF-Token':csrf,'X-Idempotency-Key':uid()})
        finally:
            c.close()
    with ThreadPoolExecutor(2) as pool:
        responses=list(pool.map(write,['并发甲','并发乙']))
    assert sorted(r.status_code for r in responses)==[200,409]
    loser=next(r for r in responses if r.status_code==409)
    assert loser.json()['error']['current_revision']==2
    body['revision']=2
    assert mutation(admin,'PATCH','/projects/'+p['id'],body,key).status_code==200
    assert mutation(admin,'PATCH','/projects/'+p['id'],body,key).json()['revision']==3


def test_transaction_rollback_leaves_no_audit_event_or_idempotency(env,monkeypatch):
    app,admin=env;store=app.state.store
    def boom(*args,**kwargs):raise RuntimeError('injected')
    monkeypatch.setattr(store,'audit',boom)
    with TestClient(app,base_url='http://127.0.0.1',raise_server_exceptions=False) as c:
        c.cookies.update(dict(admin.cookies));csrf=admin.get('/api/session').json()['csrf']
        r=c.post('/api/projects',json={'code':'P1','name':'应回滚'},headers={'X-CSRF-Token':csrf,'X-Idempotency-Key':uid()})
        assert r.status_code==500 and 'injected' not in r.text
    with store.transaction() as db:
        assert db.scalar(select(func.count()).select_from(Project))==0
        assert db.scalar(select(func.count()).select_from(Outbox))==0
        assert db.scalar(select(func.count()).select_from(Idempotency))==0


def test_outbox_delivers_once_and_recovers_in_new_store(env):
    app,admin=env;p=add_project(admin);store=app.state.store
    replacement=Store(str(store.engine.url));replacement.migrate()
    assert replacement.drain()==1
    assert replacement.drain()==0
    with replacement.transaction() as db:
        assert db.scalar(select(func.count()).select_from(Todo))==1
        assert db.scalar(select(Outbox)).state=='done'
    replacement.engine.dispose()


def test_delivery_failure_records_limited_retry_and_no_partial_todo(env,monkeypatch):
    app,admin=env;add_project(admin);store=app.state.store
    original=store.deliver
    def boom(db,event):
        original(db,event)
        raise RuntimeError('injected after write')
    monkeypatch.setattr(store,'deliver',boom)
    for count in range(1,4):
        store.drain()
        with store.transaction(write=True) as db:
            e=db.scalar(select(Outbox));assert e.attempts==count
            assert e.state==('failed' if count==3 else 'pending')
            assert db.scalar(select(func.count()).select_from(Todo))==0
            e.available_at='2000-01-01T00:00:00+00:00'
    assert store.drain()==0


def test_migration_is_idempotent_and_foreign_key_is_enforced(env):
    app,_=env;store=app.state.store;store.migrate();store.migrate()
    assert 'pilot_accounts' in inspect(store.engine).get_table_names()
    assert 'entities' not in inspect(store.engine).get_table_names()
    with pytest.raises(IntegrityError):
        with store.transaction(write=True) as db:
            db.add(Membership(id=uid(),project_id='missing',account_id='missing',roles=['市场'],valid_from='2020'))


def test_login_limit_logout_and_expired_session(env):
    app,admin=env;a=add_account(admin);alice=user_client(app,'alice');s=alice.get('/api/session').json()
    assert alice.post('/api/auth/logout',headers={'X-CSRF-Token':s['csrf']}).status_code==200
    assert alice.get('/api/session').status_code==401
    login(alice,'alice')
    with app.state.store.transaction(write=True) as db:
        token=hashlib.sha256(alice.cookies['mideng_pilot_session'].encode()).hexdigest()
        db.get(Session,token).expires_at='2000-01-01T00:00:00+00:00'
    assert alice.get('/api/session').status_code==401
    for _ in range(8):
        assert alice.post('/api/auth/login',json={'username':'alice','password':'wrong'}).status_code==401
    assert alice.post('/api/auth/login',json={'username':'alice','password':'wrong'}).status_code==429
    alice.close()


@pytest.mark.parametrize('path',['/api/providers','/api/collaboration/board','/api/state','/api/chat','/api/knowledge-bases'])
def test_legacy_unscoped_and_model_routers_are_not_mounted(env,path):
    app,admin=env
    assert app.state.model_enabled is False
    assert admin.get('/api/runtime').json()['model_enabled'] is False
    assert admin.get(path).status_code==404


def test_policy_is_explicit_and_malformed_or_missing_policy_fails_closed(tmp_path):
    good={'schema_version':1,'product':'密灯','model_enabled':False,'decision':'Q3=A','application':'app.pilot:app'}
    p=tmp_path/'policy.json';p.write_text(json.dumps(good));assert read_policy(p)['model_enabled'] is False
    p.write_text(json.dumps(good|{'model_enabled':True}));assert read_policy(p)['model_enabled'] is True
    for change in [{'product':'其他'},{'model_enabled':'false'},{'decision':'unknown'}]:
        p.write_text(json.dumps(good|change))
        with pytest.raises(ValueError):read_policy(p)
    with pytest.raises(FileNotFoundError):read_policy(tmp_path/'missing')


def test_shared_checker_preserves_other_products_and_enabled_models(tmp_path):
    import subprocess
    import shutil
    import sys
    product=Path(__file__).resolve().parents[2]
    checker=product/'scripts/model-policy-check.py'
    folder=tmp_path/'product';(folder/'backend/app').mkdir(parents=True)
    shutil.copy(product/'backend/app/pilot_policy.py',folder/'backend/app/pilot_policy.py')
    def run(name='密灯'):
        r=subprocess.run([sys.executable,str(checker),name,str(folder)],capture_output=True,text=True)
        return r.stdout.strip(),r.returncode
    assert run()==('required',0)
    policy=json.loads((product/'verification-policy.json').read_text())
    (folder/'verification-policy.json').write_text(json.dumps(policy))
    assert run()==('disabled',0)
    assert run('其他产品')==('required',0)
    (folder/'verification-policy.json').write_text(json.dumps(policy|{'model_enabled':True}))
    assert run()==('required',0)
    (folder/'verification-policy.json').write_text('{}')
    assert run()==('invalid',1)


def test_access_denial_is_audited_without_leaking_target_content(env):
    app,admin=env;add_account(admin);p=add_project(admin);alice=user_client(app,'alice')
    assert alice.get('/api/projects/'+p['id']).status_code==404
    with app.state.store.transaction() as db:
        v=db.scalar(select(Audit).where(Audit.action=='access.denied'))
        assert v is not None and v.project_id is None and p['id'] not in v.object_id
    alice.close()


def test_shared_verifier_runs_original_model_rules_when_needed(tmp_path):
    import shutil
    import subprocess
    product=Path(__file__).resolve().parents[2]
    kit=product/'tools/kit'
    shutil.copy(kit/'verify.sh',tmp_path/'verify.sh')
    for name,setting,want in [('密灯',False,'N/A（密灯 Q3=A'),('其他产品',False,'待验（缺冒烟记录）')]:
        folder=tmp_path/'projects'/name
        (folder/'scripts').mkdir(parents=True)
        (folder/'backend/app').mkdir(parents=True)
        shutil.copy(product/'scripts/model-policy-check.py',folder/'scripts/model-policy-check.py')
        shutil.copy(product/'backend/app/pilot_policy.py',folder/'backend/app/pilot_policy.py')
        policy=json.loads((product/'verification-policy.json').read_text())|{'model_enabled':setting}
        (folder/'verification-policy.json').write_text(json.dumps(policy))
        result=subprocess.run(['bash',str(tmp_path/'verify.sh'),name,'阶段2-1'],capture_output=True,text=True)
        assert want in result.stdout
    folder=tmp_path/'projects/密灯'
    policy['model_enabled']=True
    (folder/'verification-policy.json').write_text(json.dumps(policy))
    result=subprocess.run(['bash',str(tmp_path/'verify.sh'),'密灯','阶段2-1'],capture_output=True,text=True)
    assert '待验（缺冒烟记录）' in result.stdout


def test_enabling_unimplemented_model_mode_refuses_application_start(monkeypatch):
    from app import pilot
    monkeypatch.setattr(pilot,'read_policy',lambda:{'model_enabled':True})
    with pytest.raises(RuntimeError,match='F10'):
        pilot.make_app()


def test_audit_role_snapshot_survives_later_membership_change(env):
    app,admin=env;a=add_account(admin);p=add_project(admin);grant(admin,p,a,['项目经理'])
    alice=user_client(app,'alice')
    assert mutation(alice,'PATCH','/projects/'+p['id'],{'name':'业务负责人修改','revision':1}).status_code==200
    assert grant(admin,p,a,['市场'],revision=1).status_code==200
    with app.state.store.transaction() as db:
        record=db.scalar(select(Audit).where(Audit.actor_id==a['id'],Audit.action=='project.edit'))
        assert record.actor_roles==['项目经理']
    alice.close()


def test_six_character_password_setup_create_and_login(tmp_path):
    app=make_app(f'sqlite:///{tmp_path / "six.db"}',worker=False)
    with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',50123)) as c:
        body={'username':'admin6','display_name':'六位密码测试','password':'abc12'}
        assert c.post('/api/setup',json=body).status_code==422
        r=c.post('/api/setup',json=body|{'password':'abc123'})
        assert r.status_code==200,r.text
        member={'username':'member6','display_name':'六位账号测试','password':'abc12'}
        assert mutation(c,'POST','/accounts',member).status_code==422
        assert mutation(c,'POST','/accounts',member|{'password':'xyz789'}).status_code==200
        assert c.post('/api/auth/login',json={'username':'member6','password':'xyz789'}).status_code==200
        assert c.post('/api/auth/login',json={'username':'admin6','password':'abc123'}).status_code==200


def test_long_existing_password_still_works_after_shorter_policy(env):
    app,c=env
    login(c,'admin')
    assert c.get('/api/session').status_code==200
