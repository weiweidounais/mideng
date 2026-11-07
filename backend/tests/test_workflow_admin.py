"""Project administrator authority retains membership, state and actual actor gates."""
from datetime import datetime,timezone
from sqlalchemy import select
from app.pilot_models import Membership,Audit
from app.change_models import ChangeAck
from test_pilot_foundation import env,mutation,grant
from test_handoff import chain,REQ,SCHEME,post as handoff_post
from test_procurement import flow,ok,create,act,get,upload,archive_data
from test_trace import trace,prepare,record,action,upload as trace_upload,get as trace_get
from test_changes import change,publish,get as change_get,act as change_act,upload as change_upload
from test_cost import cost,board as cost_board,checked,commit,setup_close,close,publish as cost_publish


def administrator(chain):
    _,admin,_,cs,people=chain
    cs['admin']=admin
    people['admin']=admin.get('/api/session').json()['account']
    return admin,people['admin']['id']


def test_admin_creates_and_publishes_both_documents_and_can_be_all_recipients(chain):
    app,admin,p,_,_=chain;_,aid=administrator(chain)
    d=ok(handoff_post(admin,p,'/documents',{'kind':'requirement','body':REQ}))
    d=ok(handoff_post(admin,p,'/documents/'+d['id']+'/publish',{'revision':d['revision'],'recipient_ids':[aid],'diff_summary':'管理员发布需求'}))
    s=ok(handoff_post(admin,p,'/documents',{'kind':'scheme','body':SCHEME,'parent_id':d['id'],'source_version_id':d['versions'][0]['id']}))
    s=ok(handoff_post(admin,p,'/documents/'+s['id']+'/publish',{'revision':s['revision'],'recipient_ids':[aid],'diff_summary':'管理员发布方案'}))
    ok(mutation(admin,'POST','/projects/'+p['id']+'/procurement/orders',{'version_id':s['versions'][0]['id'],'title':'管理员全流程','note':'合成验收','lines':[{'material':'管材','spec':'DN100','quantity':'0.3','unit':'米','need_by':'2026-12-01'}],'purchase_id':aid,'quality_id':aid,'commerce_id':aid}))
    with app.state.store.transaction() as db:
        assert db.scalar(select(Membership).where(Membership.project_id==p['id'],Membership.account_id==aid)).roles==['管理员']
        rows=db.scalars(select(Audit).where(Audit.project_id==p['id'],Audit.action.like('document.%'))).all()
        assert rows and all(x.actor_id==aid and x.actor_roles==['管理员'] for x in rows)


def test_admin_takes_over_assigned_purchase_without_skipping_gates_or_faking_owner(flow):
    chain,_=flow;_,admin,p,_,people=chain;_,aid=administrator(chain)
    o=ok(create(flow));assert act(flow,o,'archive','admin').status_code==409
    ok(act(flow,o,'accept_purchase','admin'));o=get(flow,'admin')
    ok(act(flow,o,'submit_result','admin',result={'supplier':'合成供应商','lines':[{'line_no':1,'quantity':'0.3','eta':'2026-12-01'}]}));o=get(flow,'admin')
    ok(act(flow,o,'approve_purchase','admin'));o=get(flow,'admin')
    assert act(flow,o,'pass_quality','admin').status_code==409
    ok(act(flow,o,'arrival','admin',arrival={'line_no':1,'quantity':'0.3','occurred_at':datetime.now(timezone.utc).isoformat()}));o=get(flow,'admin')
    assert act(flow,o,'pass_quality','admin').status_code==422
    proof=ok(upload(flow,o,'admin'));ok(act(flow,o,'pass_quality','admin',file_ids=[proof['id']]));o=get(flow,'admin')
    contract=ok(upload(flow,o,'admin','archive',b'synthetic admin contract','contract.md'))
    ok(act(flow,o,'archive','admin',archive=archive_data(contract['id'])));o=get(flow,'admin')
    assert o['state']=='archived' and o['archive_total']=='1000.30'
    assert o['purchase_id']==people['purchase']['id'] and o['pm_id']==people['pm']['id']
    assert all(e['actor_id']==aid for e in o['events'] if e['action']!='request')
    assert admin.get('/api/projects/'+p['id']+'/procurement/files/'+contract['id']).status_code==200
    ok(grant(admin,p,{'id':aid},['管理员'],revision=1,active=False))
    assert admin.get('/api/projects/'+p['id']+'/procurement/board').status_code==404


def test_admin_trace_takeover_preserves_quality_evidence_and_actual_actor(trace):
    _,aid=administrator(trace['env']);prepare(trace,welding=False,pressure=False)
    assert action(trace,'start','admin').status_code==409
    ok(record(trace,'material',{'batch':'ADMIN-BATCH'},who='admin',file_ids=[trace_upload(trace,'admin')]))
    ok(action(trace,'start','admin'))
    ok(record(trace,'fabrication',{'equipment':'SYN-EQ','description':'管理员实际登记'},who='admin'))
    ok(action(trace,'submit_inspection','admin'))
    assert action(trace,'inspect','admin',passed=True,reason='缺少原件',weld_ids=[]).status_code==422
    ok(action(trace,'inspect','admin',passed=True,reason='管理员核对原件',file_ids=[trace_upload(trace,'admin')],weld_ids=[]))
    ok(action(trace,'ship','admin',location='合成库位',reference='ADMIN-SHIP',occurred_at=datetime.now(timezone.utc).isoformat()))
    ok(action(trace,'install','admin',location='合成现场',reference='ADMIN-INSTALL',occurred_at=datetime.now(timezone.utc).isoformat()))
    ok(action(trace,'complete','admin',reason='管理员核对完整履历'))
    s=trace_get(trace);assert s['state']=='completed'
    assert all(e['actor_id']==aid for e in s['events'] if e['action']!='create')


def test_admin_change_takeover_cannot_confirm_for_frozen_receivers(change):
    flow,_,_,_=change;chain,_=flow;app,_,_,_,_=chain;_,aid=administrator(chain)
    publish(change)
    ok(change_act(change,'ack','admin'))
    c=change_get(change,'admin');assert c['current']['self_confirmed']
    assert all(not r['confirmed_at'] for r in c['current']['receipts'])
    t=c['current']['body']['targets'][0]
    ok(change_act(change,'plan','admin',target_key=t['key'],decision='continue',reason='管理员登记处置依据'))
    f=ok(change_upload(change,'admin','execution'))
    ok(change_act(change,'execute','admin',target_key=t['key'],reason='管理员实际执行并留证',file_ids=[f['id']]))
    ok(change_act(change,'verify','admin',target_key=t['key']))
    assert change_act(change,'request_close','admin').status_code==409
    with app.state.store.transaction() as db:
        acks=db.scalars(select(ChangeAck).where(ChangeAck.version_id==c['current']['id'])).all()
        assert [a.actor_id for a in acks]==[aid]


def test_admin_can_finance_close_with_original_controls_and_no_membership_expansion(cost):
    admin=cost['admin'];cost['cs']['finance']=admin
    data=cost_board(cost);assert data['can_finance'] and data['can_summary']
    batch=checked(cost);ok(commit(cost,batch));setup_close(cost)
    cl=close(cost);cost_publish(cost,cl)
    assert cost_board(cost)['snapshots']


def test_technical_account_flag_alone_does_not_grant_workflow_admin(chain):
    _,admin,p,_,_=chain;aid=admin.get('/api/session').json()['account']['id']
    ok(grant(admin,p,{'id':aid},['采购'],revision=1))
    assert handoff_post(admin,p,'/documents',{'kind':'requirement','body':REQ}).status_code==403
    view=admin.get('/api/projects/'+p['id']).json()
    assert view['roles']==['采购'] and 'cost.detail' not in view['actions']


def test_admin_financial_exception_and_explicit_sensitive_export_scope(cost):
    import io,json,zipfile
    from test_cost import row
    from test_assurance import board,act,export
    from app.evidence_export import package
    from app.assurance_models import EvidenceExport
    checked(cost,[row(unit='')]);cost['cs']['admin']=cost['admin']
    exceptions=board(cost,'admin')['exceptions'];e=next(e for e in exceptions if e['financial'])
    assert e['can_manage']
    ok(act(cost,e,'read',who='admin'))
    public=export(cost,'admin',sensitive=False);sensitive=export(cost,'admin',sensitive=True)
    admin_id=cost['admin'].get('/api/session').json()['account']['id']
    from app.pilot_models import Account
    with cost['app'].state.store.transaction() as db:
        a=db.get(Account,admin_id)
        raw_zip=package(cost['app'].state.store,db,a,db.get(EvidenceExport,public['id']))
        full_zip=package(cost['app'].state.store,db,a,db.get(EvidenceExport,sensitive['id']))
        with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:raw=json.loads(archive.read('objects.json'))
        with zipfile.ZipFile(io.BytesIO(full_zip)) as archive:full=json.loads(archive.read('objects.json'))
        assert '财务' not in raw['scope']['roles'] and '财务' in full['scope']['roles']
        assert not any(x['financial'] for x in raw['exceptions'])
        assert any(x['financial'] for x in full['exceptions'])


def test_admin_may_confirm_and_apply_template_when_order_quality_is_another_actor(trace):
    from test_trace import post as trace_post,base as trace_base
    admin,_=administrator(trace['env']);prepare(trace,welding=False,pressure=False)
    t=ok(trace_post(trace,'admin','/templates',{'name':'管理员确认模板','scope':'合成','welding':False,'pressure':False,'basis':'管理员按质量岗位确认'}))
    url='/api'+trace_base(trace)+'/workspace/choices?kind=templates&order_id='+trace['order']['id']
    assert t['id'] in [x['id'] for x in admin.get(url).json()['items']]
    payload={'code':'SP-ADMIN','order_id':trace['order']['id'],'template_id':t['id']}
    assert trace_post(trace,'factory','/spools',payload).status_code==422
    ok(trace_post(trace,'admin','/spools',payload))
