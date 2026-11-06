import uuid,json
from datetime import datetime,timezone,timedelta
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,text
from sqlalchemy.exc import DatabaseError
from app.procurement_models import PurchaseOrder,PurchaseEvent
from test_handoff import chain,scheme,post as oldpost
from test_pilot_foundation import add_account,grant,login,mutation

@pytest.fixture
def flow(chain):
    app,admin,p,cs,people=chain
    person=add_account(admin,'quality');people['quality']=person
    assert grant(admin,p,person,['质量']).status_code==200
    c=TestClient(app,base_url='http://127.0.0.1');login(c,'quality');cs['quality']=c
    _,s=scheme(chain)
    yield chain,s

def base(p):return '/projects/'+p['id']+'/procurement'
def create(flow,who='pm',key=None):
    (_,_,p,cs,people),s=flow
    return mutation(cs[who],'POST',base(p)+'/orders',{'version_id':s['versions'][0]['id'],'title':'材料采购申请','note':'数量与交期按正式BOM核对','purchase_id':people['purchase']['id'],'quality_id':people['quality']['id'],'commerce_id':people['biz']['id']},key)
def get(flow,who='pm'):
    (_,_,p,cs,_),_=flow;r=cs[who].get('/api'+base(p)+'/board');assert r.status_code==200,r.text;return r.json()['orders'][0]
def act(flow,o,action,who,**extra):
    (_,_,p,cs,_),_=flow;key=extra.pop('key',None)
    return mutation(cs[who],'POST',base(p)+'/orders/'+o['id']+'/actions',{'revision':o['revision'],'action':action,**extra},key)
def ok(r):assert r.status_code==200,r.text;return r.json()
def step(flow,o,action,who,**extra):ok(act(flow,o,action,who,**extra));return get(flow)
def result(flow):
    o=step(flow,ok(create(flow)),'accept_purchase','purchase');return step(flow,o,'submit_result','purchase',result={'supplier':'合成供应商','lines':[{'line_no':1,'quantity':'0.3','eta':'2026-12-01'}]})
def approved(flow):return step(flow,result(flow),'approve_purchase','pm')
def arrival(flow,o,quantity,**extra):return act(flow,o,'arrival','purchase',arrival={'line_no':1,'quantity':quantity,'occurred_at':datetime.now(timezone.utc).isoformat()},**extra)
def upload(flow,o,who,purpose='quality',content=b'test original report',name='report.md'):
    (_,_,p,cs,_),_=flow;c=cs[who]
    return c.post('/api'+base(p)+'/orders/'+o['id']+'/files',data={'purpose':purpose},files={'file':(name,content,'text/plain')},headers={'X-CSRF-Token':c.get('/api/session').json()['csrf'],'X-Idempotency-Key':uuid.uuid4().hex})
def archive_data(fid):return {'contract_no':'TEST-ARCHIVE','tax_basis':'含税','contract_amount':'1234.56','costs':[{'name':'材料采购','amount':'1000.10'},{'name':'运费','amount':'0.20'}],'file_ids':[fid]}

def test_pm_request_purchase_cannot_skip_stages(flow):
    assert create(flow,'design').status_code==403
    o=ok(create(flow));assert get(flow)['state']=='requested'
    assert act(flow,o,'approve_purchase','pm').status_code==409
    assert act(flow,o,'accept_purchase','biz').status_code==403
    assert act(flow,o,'arrival','quality',arrival={'line_no':1,'quantity':'0.3','occurred_at':datetime.now(timezone.utc).isoformat()}).status_code==409
    assert create(flow).status_code==409

def test_request_idempotency_and_cas(flow):
    first=ok(create(flow,key='request-create-v2'));assert first==ok(create(flow,key='request-create-v2'))
    ok(act(flow,first,'accept_purchase','purchase',key='accept-retry-v2'));ok(act(flow,first,'accept_purchase','purchase',key='accept-retry-v2'))
    assert act(flow,first,'return_request','purchase',reason='late').status_code==409
    assert get(flow)['revision']==2

def test_full_flow_quality_then_private_commercial_archive(flow):
    (app,_,p,cs,_),_=flow;o=approved(flow)
    ok(arrival(flow,o,'0.1'));o=get(flow)
    assert o['state']=='quality_wait' and act(flow,o,'pass_quality','quality').status_code==409
    ok(arrival(flow,o,'0.2'));o=get(flow);assert o['state']=='quality_check'
    assert act(flow,o,'pass_quality','quality').status_code==422
    report=ok(upload(flow,o,'quality'));o=step(flow,o,'pass_quality','quality',file_ids=[report['id']]);assert o['state']=='business_archive'
    assert act(flow,o,'archive','pm',archive=archive_data(report['id'])).status_code==403
    f=ok(upload(flow,o,'biz','archive',b'synthetic procurement contract','contract.md'))
    assert act(flow,o,'archive','biz',archive=archive_data(report['id'])).status_code==422
    o=step(flow,o,'archive','biz',archive=archive_data(f['id']));assert o['state']=='archived' and o['archive'] is None
    secret=get(flow,'biz');assert secret['archive']['contract_amount']=='1234.56' and Decimal(secret['archive_total'])==Decimal('1000.30')
    for who in ['pm','purchase','design','quality']:
        public=get(flow,who);assert public['archive'] is None and public['archive_total'] is None
        assert f['id'] not in [x['id'] for x in public['files']]
        assert '1234.56' not in json.dumps(public)
        assert cs[who].get('/api'+base(p)+'/files/'+f['id']).status_code==404
    assert cs['biz'].get('/api'+base(p)+'/files/'+f['id']).content==b'synthetic procurement contract'
    assert upload(flow,o,'biz','archive').status_code==409
    with app.state.store.transaction() as db:assert len(db.scalars(select(PurchaseEvent)).all())==8

def test_result_validation_pm_difference_confirmation(flow):
    o=step(flow,ok(create(flow)),'accept_purchase','purchase')
    assert act(flow,o,'submit_result','purchase').status_code==422
    assert act(flow,o,'submit_result','purchase',result={'supplier':'合成','lines':[{'line_no':2,'quantity':'1','eta':'2026-12-01'}]}).status_code==422
    payload={'supplier':'合成','lines':[{'line_no':1,'quantity':'0.4','eta':'2026-12-01'}]}
    assert act(flow,o,'submit_result','purchase',result=payload).status_code==422
    o=step(flow,o,'submit_result','purchase',result=payload|{'note':'额外损耗0.1，需明确核准'})
    assert act(flow,o,'approve_purchase','pm').status_code==422
    assert step(flow,o,'approve_purchase','pm',reason='已核对并接受损耗')['state']=='quality_wait'

def test_return_resubmit_keep_evidence(flow):
    o=ok(create(flow));assert act(flow,o,'return_request','purchase').status_code==422
    o=step(flow,o,'return_request','purchase',reason='需补充交期说明');o=step(flow,o,'resubmit_request','pm',reason='补充按BOM日期交付');o=step(flow,o,'accept_purchase','purchase')
    o=step(flow,o,'submit_result','purchase',result={'supplier':'合成','lines':[{'line_no':1,'quantity':'0.3','eta':'2026-12-01'}]})
    o=step(flow,o,'reject_purchase','pm',reason='请补正供应说明');assert o['state']=='purchasing'
    assert [e['action'] for e in o['events']]==['request','return_request','resubmit_request','accept_purchase','submit_result','reject_purchase']

def test_arrival_exact_bounded_idempotent_not_future(flow):
    o=approved(flow);batch={'line_no':1,'quantity':'0.1','occurred_at':datetime.now(timezone.utc).isoformat()};ok(act(flow,o,'arrival','purchase',arrival=batch,key='arrival-batch-v2'));ok(act(flow,o,'arrival','purchase',arrival=batch,key='arrival-batch-v2'));assert act(flow,o,'arrival','purchase',arrival=batch|{'quantity':'0.2'},key='arrival-batch-v2').status_code==409;o=get(flow)
    assert len(o['arrivals'])==1 and arrival(flow,o,'0.3').status_code==422
    assert act(flow,o,'arrival','purchase',arrival={'line_no':1,'quantity':'0.2','occurred_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}).status_code==422
    ok(arrival(flow,o,'0.2'));assert get(flow)['state']=='quality_check'

def test_quality_failure_rectification_retest_no_auto_pass(flow):
    o=approved(flow);ok(arrival(flow,o,'0.3'));o=get(flow);f=ok(upload(flow,o,'quality'))
    o=step(flow,o,'fail_quality','quality',reason='检验不合格',file_ids=[f['id']]);assert o['state']=='quality_rework'
    assert act(flow,o,'archive','biz',archive=archive_data(f['id'])).status_code==409
    fix=ok(upload(flow,o,'purchase',content=b'rectification report'));o=step(flow,o,'rectify','purchase',reason='已完成整改，请复检',file_ids=[fix['id']]);assert o['state']=='quality_check'
    retest=ok(upload(flow,o,'quality',content=b'retest report'));o=step(flow,o,'pass_quality','quality',file_ids=[retest['id']]);assert o['state']=='business_archive'
    assert len([e for e in o['events'] if e['action'] in {'fail_quality','rectify','pass_quality'}])==3

def test_source_withdrawal_cross_project_guesses(flow):
    (_,_,p,cs,_),s=flow;o=result(flow)
    assert oldpost(cs['design'],p,'/documents/'+s['id']+'/withdraw',{'revision':s['revision'],'reason':'需复核方案'}).status_code==200
    assert act(flow,o,'approve_purchase','pm').status_code==409 and get(flow)['needs_review']
    assert cs['outsider'].get('/api'+base(p)+'/board').status_code==404
    assert act(flow,o,'approve_purchase','outsider').status_code==404

def test_immutable_events_and_transaction_rollback(flow,monkeypatch):
    (app,_,_,_,_),_=flow
    from app import procurement_service
    original=procurement_service.record
    def broken(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('injected write failure')
    monkeypatch.setattr(procurement_service,'record',broken)
    with pytest.raises(RuntimeError):create(flow)
    with app.state.store.transaction() as db:assert not db.scalars(select(PurchaseOrder)).all()
    monkeypatch.setattr(procurement_service,'record',original);ok(create(flow))
    with pytest.raises(DatabaseError):
        with app.state.store.transaction(write=True) as db:db.execute(text("UPDATE procurement_events SET action='forged'"))

def test_same_role_wrong_recipient_blocked(flow):
    (app,admin,p,cs,_),_=flow;o=ok(create(flow))
    person=add_account(admin,'other-purchase');assert grant(admin,p,person,['采购']).status_code==200
    with TestClient(app,base_url='http://127.0.0.1') as other:
        login(other,'other-purchase')
        assert mutation(other,'POST',base(p)+'/orders/'+o['id']+'/actions',{'revision':1,'action':'accept_purchase'}).status_code==403
    assert get(flow)['state']=='requested'

def test_report_type_and_hash(flow):
    (app,_,p,cs,_),_=flow;o=approved(flow);ok(arrival(flow,o,'0.3'));o=get(flow)
    assert upload(flow,o,'quality',name='../x.md').status_code==422
    assert upload(flow,o,'quality',name='fake.pdf').status_code==422
    f=ok(upload(flow,o,'quality'))
    from app.procurement_models import PurchaseFile
    from pathlib import Path
    with app.state.store.transaction() as db:file_path=db.get(PurchaseFile,f['id']).path
    Path(file_path).write_bytes(b'tampered')
    assert act(flow,o,'pass_quality','quality',file_ids=[f['id']]).status_code==409
    assert cs['quality'].get('/api'+base(p)+'/files/'+f['id']).status_code==409

def test_node_overdue_issue_tracks_current_owner_and_todo(flow):
    from app.handoff_service import reconcile
    from app.handoff_models import Issue
    from app.pilot_models import Outbox
    (app,_,p,_,people),_=flow;o=result(flow)
    with app.state.store.transaction(write=True) as db:
        order=db.get(PurchaseOrder,o['id']);order.due_at=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        reconcile(db,p['id'])
        issues=db.scalars(select(Issue).where(Issue.object_id==o['id'],Issue.active.is_(True))).all()
        assert len(issues)==1 and issues[0].owner_id==people['pm']['id']
        assert db.scalar(select(Outbox).where(Outbox.target_id==o['id'],Outbox.recipient_id==people['pm']['id']))
    o=step(flow,o,'approve_purchase','pm')
    with app.state.store.transaction() as db:
        assert not db.scalars(select(Issue).where(Issue.object_id==o['id'],Issue.active.is_(True))).all()
