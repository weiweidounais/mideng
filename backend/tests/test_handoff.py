"""Real SQLite and multi-account HTTP tests for the published-version handoff chain."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,update,func,text
from sqlalchemy.exc import IntegrityError,DatabaseError
from app.pilot import make_app
from app.pilot_models import Account,Outbox,Todo
from app.handoff_models import Document,Version,Contract,MaterialRow,Arrival,Attachment,Issue,BusinessEvent
from app.handoff_service import reconcile
from test_pilot_foundation import mutation,login,add_account,add_project,grant,PASS

REQ={'title':'试点需求','summary':'按正式图纸交付','constraints':'满足质量规范','source':'脱敏甲方交底记录'}
BOM=[{'material':'管材','spec':'DN100','quantity':'0.3','unit':'米','need_by':'2026-12-01'}]
SCHEME={'title':'设计方案','notes':'按现行需求和图纸执行','risks':'注意交期','bom':BOM}

@pytest.fixture
def chain(tmp_path):
    app=make_app(f'sqlite:///{tmp_path/"business.db"}',worker=False)
    with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',1234)) as admin:
        assert admin.post('/api/setup',json={'username':'admin','display_name':'测试管理员','password':PASS}).status_code==200
        p=add_project(admin);clients={};people={}
        for name,role in [('market','市场'),('biz','商务'),('design','设计'),('purchase','采购'),('pm','项目经理'),('outsider','市场')]:
            person=add_account(admin,name);people[name]=person
            if name!='outsider':assert grant(admin,p,person,[role]).status_code==200
            c=TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',1234));login(c,name);clients[name]=c
        yield app,admin,p,clients,people
        for c in clients.values():c.close()


def path(p,s):return '/projects/'+p['id']+'/handoff'+s

def post(c,p,s,b,key=None):return mutation(c,'POST',path(p,s),b,key)

def board(c,p):
    r=c.get('/api'+path(p,'/board'));assert r.status_code==200,r.text;return r.json()

def req(chain):
    _,_,p,cs,people=chain
    r=post(cs['market'],p,'/documents',{'kind':'requirement','body':REQ});assert r.status_code==200,r.text
    d=r.json();r=post(cs['biz'],p,'/documents/'+d['id']+'/publish',{'revision':d['revision'],'recipient_ids':[people['design']['id']],'diff_summary':'首次交底'})
    assert r.status_code==200,r.text;return r.json()

def scheme(chain):
    _,_,p,cs,people=chain;d=req(chain)
    r=post(cs['design'],p,'/documents',{'kind':'scheme','parent_id':d['id'],'source_version_id':d['versions'][0]['id'],'body':SCHEME});assert r.status_code==200,r.text;s=r.json()
    r=post(cs['design'],p,'/documents/'+s['id']+'/publish',{'revision':s['revision'],'recipient_ids':[people['pm']['id']],'diff_summary':'首次方案/BOM'})
    assert r.status_code==200,r.text;return d,r.json()

def contract(chain):
    _,_,p,cs,people=chain;d,s=scheme(chain)
    r=post(cs['design'],p,'/contracts',{'version_id':s['versions'][0]['id'],'recipient_id':people['purchase']['id'],'deliverable':'完整BOM','quality_rule':'规格/单位/数量/需用日期核对','require_arrival':True})
    assert r.status_code==200,r.text;return d,s,r.json()

def action(chain,c,name,who='design',**kw):
    _,_,p,cs,_=chain;r=post(cs[who],p,'/contracts/'+c['id']+'/actions',{'revision':c['revision'],'action':name,**kw})
    assert r.status_code==200,r.text;return r.json()


def test_draft_visibility_role_and_project_guesses(chain):
    app,admin,p,cs,people=chain
    d=post(cs['market'],p,'/documents',{'kind':'requirement','body':REQ}).json()
    assert not board(cs['purchase'],p)['documents']
    assert cs['purchase'].get('/api'+path(p,'/documents/'+d['id'])).status_code==404
    assert post(cs['market'],p,'/documents/'+d['id']+'/publish',{'revision':1,'recipient_ids':[people['design']['id']],'diff_summary':'禁止越权'}).status_code==403
    assert cs['outsider'].get('/api'+path(p,'/board')).status_code==404
    other=add_project(admin,'OTHER')
    assert cs['market'].get('/api'+path(other,'/documents/'+d['id'])).status_code==404


def test_publish_freezes_version_repeated_publish_and_revision_conflict(chain):
    app,_,p,cs,people=chain;key='publish-idempotency'
    d=post(cs['market'],p,'/documents',{'kind':'requirement','body':REQ}).json()
    body={'revision':1,'recipient_ids':[people['design']['id']],'diff_summary':'发布依据'}
    a=post(cs['biz'],p,'/documents/'+d['id']+'/publish',body,key);b=post(cs['biz'],p,'/documents/'+d['id']+'/publish',body,key)
    assert a.status_code==200 and a.json()==b.json()
    assert post(cs['biz'],p,'/documents/'+d['id']+'/publish',body|{'diff_summary':'异载荷'},key).status_code==409
    assert mutation(cs['market'],'PATCH',path(p,'/documents/'+d['id']),{'revision':2,'body':REQ|{'summary':'覆盖正式版'}}).status_code==409
    with app.state.store.transaction() as db:
        assert db.scalar(select(func.count()).select_from(Version))==1
        version=db.scalar(select(Version))
        assert version.body['summary']==REQ['summary']
    assert board(cs['purchase'],p)['documents'][0]['draft'] is None


def test_scheme_requires_valid_formal_requirement_and_recipients(chain):
    _,_,p,cs,people=chain;d=req(chain)
    bad=post(cs['design'],p,'/documents',{'kind':'scheme','parent_id':d['id'],'source_version_id':'missing','body':SCHEME})
    assert bad.status_code==404
    r=post(cs['design'],p,'/documents',{'kind':'scheme','parent_id':d['id'],'source_version_id':d['versions'][0]['id'],'body':SCHEME});s=r.json()
    assert post(cs['design'],p,'/documents/'+s['id']+'/publish',{'revision':1,'recipient_ids':[people['market']['id']],'diff_summary':'缺采购'}).status_code==422


def test_full_handoff_return_accept_partial_arrival_and_close(chain):
    app,_,p,cs,_=chain;_,_,c=contract(chain)
    c=action(chain,c,'issue');c=action(chain,c,'submit')
    assert post(cs['purchase'],p,'/contracts/'+c['id']+'/actions',{'revision':c['revision'],'action':'return'}).status_code==422
    c=action(chain,c,'return','purchase',reason='缺少交付说明');assert c['state']=='pending' and c['return_count']==1
    c=action(chain,c,'submit');c=action(chain,c,'accept','purchase');assert c['state']=='accepted'
    row=board(cs['purchase'],p)['rows'][0]
    r=mutation(cs['purchase'],'PATCH',path(p,'/rows/'+row['id']),{'revision':row['revision'],'state':'ordered','eta':'2026-12-01'});assert r.status_code==200,r.text;row=r.json()
    now=datetime.now(timezone.utc).isoformat();body={'revision':row['revision'],'quantity':'0.1','occurred_at':now}
    first=post(cs['purchase'],p,'/rows/'+row['id']+'/arrivals',body,'arrival-repeat-01');again=post(cs['purchase'],p,'/rows/'+row['id']+'/arrivals',body,'arrival-repeat-01')
    assert first.status_code==200 and first.json()==again.json();row=first.json();assert row['state']=='ordered' and row['arrived']=='0.1'
    assert post(cs['purchase'],p,'/contracts/'+c['id']+'/actions',{'revision':c['revision'],'action':'close'}).status_code==422
    r=post(cs['purchase'],p,'/rows/'+row['id']+'/arrivals',{'revision':row['revision'],'quantity':'0.2','occurred_at':now});assert r.status_code==200,r.text
    assert r.json()['arrived']=='0.3' and r.json()['state']=='arrived'
    c=action(chain,c,'close','purchase');assert c['state']=='closed'
    with app.state.store.transaction() as db:assert db.scalar(select(func.count()).select_from(Arrival))==2


def test_new_requirement_draft_keeps_old_source_until_publish_then_requires_review(chain):
    _,_,p,cs,people=chain;d,s,c=contract(chain);c=action(chain,c,'issue')
    d=post(cs['market'],p,'/documents/'+d['id']+'/revise',{'revision':d['revision']}).json()
    d=mutation(cs['market'],'PATCH',path(p,'/documents/'+d['id']),{'revision':d['revision'],'body':REQ|{'summary':'新需求'}}).json()
    assert not board(cs['design'],p)['contracts'][0]['needs_review']
    d=post(cs['biz'],p,'/documents/'+d['id']+'/publish',{'revision':d['revision'],'recipient_ids':[people['design']['id']],'diff_summary':'甲方修订'}).json()
    assert d['versions'][1]['body']['summary']==REQ['summary']
    assert board(cs['design'],p)['contracts'][0]['needs_review']
    assert post(cs['design'],p,'/contracts/'+c['id']+'/actions',{'revision':c['revision'],'action':'submit'}).status_code==409
    s=post(cs['design'],p,'/documents/'+s['id']+'/revise',{'revision':s['revision']}).json()
    body={'revision':s['revision'],'body':SCHEME,'source_version_id':d['versions'][0]['id']}
    assert mutation(cs['design'],'PATCH',path(p,'/documents/'+s['id']),body).status_code==422
    body['body']=SCHEME|{'review_reason':'已复核新增约束，方案仍适用'}
    s=mutation(cs['design'],'PATCH',path(p,'/documents/'+s['id']),body).json()
    s=post(cs['design'],p,'/documents/'+s['id']+'/publish',{'revision':s['revision'],'recipient_ids':[people['pm']['id']],'diff_summary':'复核后重新发布'}).json()
    assert s['versions'][0]['current'] and not s['versions'][1]['current']


def test_pause_resume_cancel_deadline_preserves_original_and_status(chain):
    _,_,p,cs,_=chain;_,_,c=contract(chain);original=c['original_due_at']
    c=action(chain,c,'issue');c=action(chain,c,'pause',reason='等待核对')
    assert c['state']=='pending' and c['paused_at']
    assert post(cs['design'],p,'/contracts/'+c['id']+'/actions',{'revision':c['revision'],'action':'submit'}).status_code==409
    c=action(chain,c,'resume',reason='已核对')
    c=action(chain,c,'reschedule',reason='调整交付',due_at=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat())
    assert c['original_due_at']==original and c['due_at']!=original
    c=action(chain,c,'cancel',reason='原交接取消，保留记录');assert c['state']=='cancelled'


def test_wrong_procurement_recipient_and_unaccepted_order_blocked(chain):
    _,admin,p,cs,_=chain;_,_,c=contract(chain);c=action(chain,c,'issue')
    stranger=add_account(admin,'purchase2');grant(admin,p,stranger,['采购']);other=TestClient(cs['purchase'].app,base_url='http://127.0.0.1');login(other,'purchase2')
    row=board(cs['purchase'],p)['rows'][0]
    assert mutation(other,'PATCH',path(p,'/rows/'+row['id']),{'revision':1,'state':'quoted'}).status_code==403
    assert mutation(cs['purchase'],'PATCH',path(p,'/rows/'+row['id']),{'revision':1,'state':'ordered'}).status_code==409
    other.close()


def test_attachment_actual_bytes_hash_draft_and_formal_permissions(chain):
    _,_,p,cs,people=chain;content='脱敏交底原件'.encode()
    headers={'X-CSRF-Token':cs['market'].get('/api/session').json()['csrf'],'X-Idempotency-Key':'upload-repeat-01'}
    r=cs['market'].post('/api'+path(p,'/files'),data={'kind':'requirement'},files={'file':('交底.md',content,'text/plain')},headers=headers)
    assert r.status_code==200,r.text;f=r.json();assert f['sha256']==hashlib.sha256(content).hexdigest()
    assert cs['purchase'].get('/api'+path(p,'/files/'+f['id'])).status_code==404
    d=post(cs['market'],p,'/documents',{'kind':'requirement','body':REQ|{'attachment_ids':[f['id']]}}).json()
    assert d['draft_files']==[f]
    assert cs['biz'].get('/api'+path(p,'/documents/'+d['id'])).json()['draft_files']==[f]
    published=post(cs['biz'],p,'/documents/'+d['id']+'/publish',{'revision':1,'recipient_ids':[people['design']['id']],'diff_summary':'含原件发布'})
    assert published.status_code==200,published.text
    got=cs['purchase'].get('/api'+path(p,'/files/'+f['id']));assert got.content==content
    assert cs['outsider'].get('/api'+path(p,'/files/'+f['id'])).status_code==404
    bad=cs['market'].post('/api'+path(p,'/files'),data={'kind':'requirement'},files={'file':('fake.pdf',b'not-pdf','application/pdf')},headers=headers|{'X-Idempotency-Key':'upload-bad-01'})
    assert bad.status_code==422
    unsafe=cs['market'].post('/api'+path(p,'/files'),data={'kind':'requirement'},files={'file':('../x.md',b'abc','text/plain')},headers=headers|{'X-Idempotency-Key':'upload-bad-02'})
    assert unsafe.status_code==422


def test_database_blocks_version_overwrite_and_cross_project_links(chain):
    app,admin,p,cs,_=chain;d=req(chain);other=add_project(admin,'OTHER')
    with pytest.raises(DatabaseError):
        with app.state.store.transaction(write=True) as db:db.execute(update(Version).values(diff_summary='覆盖'))
    with pytest.raises(IntegrityError):
        with app.state.store.transaction(write=True) as db:
            db.add(Document(id='invalid-link',project_id=other['id'],kind='scheme',parent_id=d['id'],source_version_id=d['versions'][0]['id'],draft=SCHEME,created_by=d['created_by'],updated_by=d['created_by']))


def test_time_labels_and_issue_recompute_do_not_destroy_contract_state(chain):
    app,_,p,cs,_=chain;_,_,c=contract(chain);c=action(chain,c,'issue')
    with app.state.store.transaction(write=True) as db:
        record=db.get(Contract,c['id']);record.due_at='2020-01-01T00:00:00+00:00';db.flush();reconcile(db,p['id']);db.flush();reconcile(db,p['id'])
        assert db.scalar(select(func.count()).select_from(Issue).where(Issue.rule.like('contract.overdue%')))==1
    v=board(cs['design'],p)['contracts'][0];assert v['state']=='pending' and v['overdue']
    c=action(chain,v,'submit')
    with app.state.store.transaction() as db:assert db.scalar(select(Issue).where(Issue.rule.like('contract.overdue%'))).active is False


def test_withdraw_requires_authority_reason_and_preserves_formal_evidence(chain):
    app,_,p,cs,_=chain;d,s,c=contract(chain)
    assert post(cs['market'],p,'/documents/'+d['id']+'/withdraw',{'revision':d['revision'],'reason':'无权'}).status_code==403
    assert post(cs['biz'],p,'/documents/'+d['id']+'/withdraw',{'revision':d['revision'],'reason':''}).status_code==422
    r=post(cs['biz'],p,'/documents/'+d['id']+'/withdraw',{'revision':d['revision'],'reason':'甲方撤回依据'})
    assert r.status_code==200,r.text
    assert r.json()['versions'][0]['withdrawn'] and not r.json()['versions'][0]['current']
    assert post(cs['design'],p,'/contracts/'+c['id']+'/actions',{'revision':c['revision'],'action':'issue'}).status_code==409
    with app.state.store.transaction() as db:
        assert db.scalar(select(func.count()).select_from(Version))==2
        assert db.get(Contract,c['id']).state=='draft'


def test_published_todo_points_to_exact_object_and_version(chain):
    app,_,p,cs,_=chain;d=req(chain);app.state.store.drain()
    todos=cs['design'].get('/api/todos').json()
    assert any(t['target_id']==d['id'] and t['version_id']==d['versions'][0]['id'] for t in todos)


def test_csv_bom_preview_reports_row_errors_and_does_not_write_business(chain):
    app,_,p,cs,_=chain
    headers={'X-CSRF-Token':cs['design'].get('/api/session').json()['csrf']}
    r=cs['design'].post('/api'+path(p,'/bom-preview'),files={'file':('bom.csv','物料,规格,数量,单位,需用日期\n管材,DN100,0.3,米,2026-12-01\n管材,DN50,-1,,2026-12-01\n'.encode())},headers=headers)
    assert r.status_code==200,r.text
    assert len(r.json()['rows'])==1 and r.json()['errors'][0]['row']==3
    with app.state.store.transaction() as db:assert db.scalar(select(func.count()).select_from(Document))==0
    assert cs['market'].post('/api'+path(p,'/bom-preview'),files={'file':('bom.csv',b'fake')},headers={'X-CSRF-Token':cs['market'].get('/api/session').json()['csrf']}).status_code==403


def test_existing_foundation_database_upgrades_without_reset(tmp_path):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    from app.pilot_service import Store,hasher
    url=f'sqlite:///{tmp_path/"existing.db"}';store=Store(url)
    cfg=Config();cfg.set_main_option('script_location',str(Path(__file__).resolve().parents[1]/'pilot_migrations'))
    with store.engine.begin() as con:
        cfg.attributes['connection']=con;command.upgrade(cfg,'pilot_002')
        con.execute(text('INSERT INTO pilot_accounts(id,username,display_name,password_hash,is_admin,active) VALUES (:id,:u,:n,:h,1,1)'),{'id':'old-admin','u':'preserved','n':'原测试账号','h':hasher.hash(PASS)})
        con.execute(text("INSERT INTO pilot_projects(id,code,name,owner_id,revision,created_at) VALUES ('old-project','OLD','已有项目','old-admin',7,'2026-01-01T00:00:00+00:00')"))
        con.execute(text("INSERT INTO pilot_memberships(id,project_id,account_id,roles,active,valid_from,revision) VALUES ('old-member','old-project','old-admin','[\"管理员\"]',1,'2026-01-01T00:00:00+00:00',1)"))
    app=make_app(url,worker=False)
    with TestClient(app,base_url='http://127.0.0.1') as c:
        assert c.get('/api/setup').json()['required'] is False
        login(c,'preserved')
        data=c.get('/api/projects').json();assert data[0]['id']=='old-project' and data[0]['revision']==7
        assert c.get('/api/projects/old-project/handoff/board').json()['documents']==[]
        with app.state.store.transaction() as db:assert db.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='pilot_011'
    store.engine.dispose()


def test_document_draft_concurrent_compare_and_swap_has_one_winner(chain):
    _,_,p,cs,_=chain;d=post(cs['market'],p,'/documents',{'kind':'requirement','body':REQ}).json()
    cookie=dict(cs['market'].cookies);csrf=cs['market'].get('/api/session').json()['csrf']
    def change(summary):
        c=TestClient(cs['market'].app,base_url='http://127.0.0.1')
        try:
            c.cookies.update(cookie)
            return c.patch('/api'+path(p,'/documents/'+d['id']),json={'revision':1,'body':REQ|{'summary':summary}},headers={'X-CSRF-Token':csrf,'X-Idempotency-Key':'draft-change-'+summary})
        finally:c.close()
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(change,['A','B']))
    assert sorted(r.status_code for r in results)==[200,409]
    current=cs['market'].get('/api'+path(p,'/documents/'+d['id'])).json()
    assert current['revision']==2 and current['draft']['summary'] in {'A','B'}


def test_publish_failure_rolls_back_version_revision_and_events(chain,monkeypatch):
    app,_,p,cs,people=chain;d=post(cs['market'],p,'/documents',{'kind':'requirement','body':REQ}).json()
    old=app.state.store.audit
    def crash(db,a,action,*args,**kw):
        if action=='document.publish':raise RuntimeError('injected')
        return old(db,a,action,*args,**kw)
    monkeypatch.setattr(app.state.store,'audit',crash)
    c=TestClient(app,base_url='http://127.0.0.1',raise_server_exceptions=False);c.cookies.update(dict(cs['biz'].cookies))
    r=post(c,p,'/documents/'+d['id']+'/publish',{'revision':1,'recipient_ids':[people['design']['id']],'diff_summary':'应原子回滚'})
    assert r.status_code==500 and 'injected' not in r.text
    with app.state.store.transaction() as db:
        assert db.scalar(select(func.count()).select_from(Version))==0
        assert db.get(Document,d['id']).revision==1 and db.get(Document,d['id']).has_draft
    c.close()


def test_missing_original_blocks_publication(chain):
    from pathlib import Path
    app,_,p,cs,people=chain;headers={'X-CSRF-Token':cs['market'].get('/api/session').json()['csrf'],'X-Idempotency-Key':'file-missing-test'}
    r=cs['market'].post('/api'+path(p,'/files'),data={'kind':'requirement'},files={'file':('test.md',b'original','text/plain')},headers=headers)
    assert r.status_code==200;fid=r.json()['id']
    d=post(cs['market'],p,'/documents',{'kind':'requirement','body':REQ|{'attachment_ids':[fid]}}).json()
    (Path(app.state.store.engine.url.database).parent/'attachments'/fid).unlink()
    r=post(cs['biz'],p,'/documents/'+d['id']+'/publish',{'revision':1,'recipient_ids':[people['design']['id']],'diff_summary':'原件缺失不可发布'})
    assert r.status_code==422 and r.json()['error']['code']=='FILE_MISSING'


def test_bulk_row_projection_keeps_exact_arrivals_without_per_row_queries(chain):
    from app.handoff_service import row_views
    from sqlalchemy import event
    from app.pilot_service import uid
    app,_,p,cs,people=chain;_,_,c=contract(chain);c=action(chain,c,'issue')
    with app.state.store.transaction(write=True) as db:
        first=db.scalar(select(MaterialRow).where(MaterialRow.contract_id==c['id']))
        for i in range(2,102):db.add(MaterialRow(id=uid(),project_id=p['id'],contract_id=c['id'],line_no=i,material='合成',spec='DN',quantity='0.3',unit='米',need_by='2026-12-01',created_by=people['design']['id'],updated_by=people['design']['id']))
        for value in ['0.1','0.2']:db.add(Arrival(id=uid(),project_id=p['id'],row_id=first.id,quantity=value,occurred_at=datetime.now(timezone.utc).isoformat(),created_by=people['purchase']['id']))
        first_id=first.id
    with app.state.store.transaction() as db:
        rows=list(db.scalars(select(MaterialRow).where(MaterialRow.project_id==p['id'])));queries=[]
        def capture(conn,cursor,statement,parameters,context,executemany):queries.append(statement)
        event.listen(app.state.store.engine,'before_cursor_execute',capture)
        try:views=row_views(db,rows)
        finally:event.remove(app.state.store.engine,'before_cursor_execute',capture)
    assert len(views)==101 and next(x for x in views if x['id']==first_id)['arrived']=='0.3'
    assert len(queries)<=2 and all(x['arrived']=='0' for x in views if x['id']!=first_id)
