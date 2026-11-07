import uuid,json
from datetime import datetime,timezone
import pytest
from sqlalchemy import select,text
from sqlalchemy.exc import DatabaseError
from app.change_models import ChangeCase,ChangeVersion,ChangeAck,ChangeDisposition
from test_procurement import flow,ok,result as proc_result,act as proc_act,get as proc_get
from test_handoff import chain,post as oldpost,path as oldpath
from test_pilot_foundation import mutation

@pytest.fixture
def change(flow):
    (app,admin,p,cs,people),s=flow;o=proc_result(flow)
    documents=cs['pm'].get('/api'+oldpath(p,'/board')).json()['documents'];d=next(d for d in documents if d['kind']=='requirement');old=d['versions'][0]
    d=ok(oldpost(cs['market'],p,'/documents/'+d['id']+'/revise',{'revision':d['revision']}))
    d=ok(mutation(cs['market'],'PATCH',oldpath(p,'/documents/'+d['id']),{'revision':d['revision'],'body':old['body']|{'summary':'新增现场约束，需专业确认旧任务处置'}}))
    d=ok(oldpost(cs['biz'],p,'/documents/'+d['id']+'/publish',{'revision':d['revision'],'recipient_ids':[people['design']['id']],'diff_summary':'业务变更来源'}))
    payload={'title':'现场技术变更','reason':'核对旧材料的执行方案','old_version_id':old['id'],'new_version_id':d['versions'][0]['id']}
    c=ok(mutation(cs['pm'],'POST',base(p),payload))
    yield flow,c,o,payload

def base(p):return '/projects/'+p['id']+'/changes'
def get(change,who='pm'):
    flow,c,_,_=change;(_,_,p,cs,_),_=flow;r=cs[who].get('/api'+base(p)+'/board');assert r.status_code==200,r.text;return next(x for x in r.json()['cases'] if x['id']==c['id'])
def act(change,action,who='pm',key=None,**extra):
    flow,c,_,_=change;(_,_,p,cs,_),_=flow;current=get(change)
    return mutation(cs[who],'POST',base(p)+'/'+c['id']+'/actions',{'revision':current['revision'],'action':action,'version_id':current['current']['id'] if current['current'] else None,**extra},key)
def upload(change,who='pm',purpose='approval',restricted=False,content=b'synthetic signed evidence',name='evidence.md'):
    flow,c,_,_=change;(_,_,p,cs,_),_=flow;client=cs[who]
    return client.post('/api'+base(p)+'/'+c['id']+'/files',data={'purpose':purpose,'restricted':str(restricted).lower()},files={'file':(name,content,'text/plain')},headers={'X-CSRF-Token':client.get('/api/session').json()['csrf'],'X-Idempotency-Key':uuid.uuid4().hex})
def impacts(change):
    for cat,who in [('technical','design'),('cost','biz'),('schedule','pm'),('quality','quality')]:ok(act(change,'impact',who,category=cat,has_impact=False,reason='已核对本专业，无额外影响'))
def publish(change):
    impacts(change);f=ok(upload(change));ok(act(change,'approval',approval_no='SYNTHETIC-APPROVAL',reason='登记既有脱敏批准',file_ids=[f['id']]))
    ok(act(change,'publish',recipient_ids=get(change)['required_recipient_ids']));return get(change)
def deliver(change):
    flow,_,_,_=change;(app,_,_,_,_),_=flow;app.state.store.drain()
def acknowledge(change,skip=None):
    flow,_,_,_=change;(_,_,_,_,people),_=flow;deliver(change)
    ids=set(get(change)['current']['body']['recipients'])
    for who in ['pm','purchase','quality','biz','design']:
        if who!=skip and people[who]['id'] in ids:ok(act(change,'ack',who))
def dispose(change):
    flow,_,_,_=change;(_,_,_,_,people),_=flow
    for t in get(change)['current']['body']['targets']:
        ok(act(change,'plan',target_key=t['key'],decision='continue',reason='按已登记批准允许继续使用旧材料'))
        who=next(k for k,v in people.items() if v['id']==t['owner_id'])
        f=ok(upload(change,who,'execution'))
        ok(act(change,'execute',who,target_key=t['key'],reason='已实际核对并关联执行证据',file_ids=[f['id']]))
        ok(act(change,'verify',target_key=t['key']))

def test_publish_requires_four_professionals_approval_and_all_receivers(change):
    assert act(change,'publish').status_code==409
    assert act(change,'impact','purchase',category='technical',has_impact=False,reason='伪造').status_code==404
    assert act(change,'impact','design',category='technical',has_impact=True,reason='有影响').status_code==422
    impacts(change)
    assert act(change,'approval',approval_no='X',reason='missing').status_code==422
    f=ok(upload(change));ok(act(change,'approval',approval_no='SYNTH',reason='登记既有批准',file_ids=[f['id']]))
    assert act(change,'publish',recipient_ids=[]).status_code==422
    ok(act(change,'publish',recipient_ids=get(change)['required_recipient_ids']))

def test_delivery_ack_and_disposition_are_independent_close_gates(change):
    publish(change)
    assert act(change,'ack').status_code==409
    acknowledge(change,skip='purchase')
    assert act(change,'request_close').status_code==409
    ok(act(change,'ack','purchase'))
    assert act(change,'request_close').status_code==409
    dispose(change);ok(act(change,'request_close'));ok(act(change,'close'))
    assert get(change)['state']=='closed'
    flow,_,o,_=change
    ok(proc_act(flow,o,'approve_purchase','pm'))
    assert proc_get(flow)['version_id']==o['version_id']

def test_published_change_blocks_old_order_until_verified_continue(change):
    publish(change);flow,_,o,_=change
    assert proc_act(flow,o,'approve_purchase','pm').status_code==409
    acknowledge(change)
    t=next(t for t in get(change)['current']['body']['targets'] if t['key'].startswith('procurement:'))
    ok(act(change,'plan',target_key=t['key'],decision='continue',reason='批准允许继续'))
    f=ok(upload(change,'purchase','execution'))
    ok(act(change,'execute','purchase',target_key=t['key'],reason='已核对完成',file_ids=[f['id']]))
    assert proc_act(flow,o,'approve_purchase','pm').status_code==409
    ok(act(change,'verify',target_key=t['key']));ok(proc_act(flow,o,'approve_purchase','pm'))

def test_new_change_version_never_reuses_old_confirmations(change):
    publish(change);acknowledge(change);old=get(change)['current']['id']
    ok(act(change,'revise',replacement=change[3]|{'reason':'补充处置规则，必须重新确认'}));publish(change)
    c=get(change);assert c['current']['id']!=old and not any(r['confirmed_at'] for r in c['current']['receipts'])
    assert all(r['confirmed_at'] for r in c['versions'][1]['receipts'])
    flow,_,_,_=change;(_,_,p,cs,_),_=flow
    r=mutation(cs['pm'],'POST',base(p)+'/'+c['id']+'/actions',{'revision':c['revision'],'action':'ack','version_id':old});assert r.status_code==409

def test_same_key_replays_once_and_rejects_changed_payload(change):
    c=publish(change);deliver(change);flow,_,_,_=change;(_,_,p,cs,_),_=flow
    body={'revision':c['revision'],'action':'ack','version_id':c['current']['id']};key='change-ack-idempotent'
    r=mutation(cs['pm'],'POST',base(p)+'/'+c['id']+'/actions',body,key);ok(r)
    assert mutation(cs['pm'],'POST',base(p)+'/'+c['id']+'/actions',body,key).json()==r.json()
    assert mutation(cs['pm'],'POST',base(p)+'/'+c['id']+'/actions',body|{'reason':'changed'},key).status_code==409

def test_private_approval_original_and_cost_text_remain_private(change):
    f=ok(upload(change,'biz',restricted=True,content=b'synthetic confidential approval'))
    flow,_,_,_=change;(_,_,p,cs,_),_=flow
    assert cs['pm'].get('/api'+base(p)+'/files/'+f['id']).status_code==404
    assert cs['biz'].get('/api'+base(p)+'/files/'+f['id']).status_code==200
    ok(act(change,'impact','biz',category='cost',has_impact=False,reason='PRIVATE-COST-CONCLUSION'))
    assert 'PRIVATE-COST-CONCLUSION' not in json.dumps(get(change))
    assert 'PRIVATE-COST-CONCLUSION' in json.dumps(get(change,'biz'))

def test_cross_project_and_immutable_published_evidence(change):
    publish(change);flow,c,_,_=change;(app,_,p,cs,_),_=flow
    assert cs['outsider'].get('/api'+base(p)+'/board').status_code==404
    assert mutation(cs['outsider'],'POST',base(p)+'/'+c['id']+'/actions',{'revision':1,'action':'close'}).status_code==404
    with pytest.raises(DatabaseError):
        with app.state.store.transaction(write=True) as db:db.execute(text("UPDATE change_versions SET number=99"))

def test_cancel_never_deletes_procurement_facts(change):
    publish(change);flow,_,o,_=change
    assert act(change,'cancel').status_code==422
    ok(act(change,'cancel',reason='撤销变更登记，旧采购事实留存待另行核定'))
    assert get(change)['state']=='cancelled' and proc_get(flow)['result'] is not None
    assert proc_act(flow,o,'approve_purchase','pm').status_code==409

def test_new_tasks_need_new_version_approval_confirmation_and_dispositions(change):
    flow,_,_,payload=change;(_,_,p,cs,people),s=flow
    new=ok(oldpost(cs['design'],p,'/documents',{'kind':'scheme','parent_id':s['parent_id'],'source_version_id':payload['new_version_id'],'body':s['versions'][0]['body']}))
    new=ok(oldpost(cs['design'],p,'/documents/'+new['id']+'/publish',{'revision':new['revision'],'recipient_ids':[people['pm']['id']],'diff_summary':'新需求对应新方案'}))
    from test_procurement import base as procbase
    body={'version_id':new['versions'][0]['id'],'title':'新任务','note':'须完成变更同步','lines':[{'material':'管材','spec':'DN100','quantity':'0.3','unit':'米','need_by':'2026-12-01'}],'purchase_id':people['purchase']['id'],'quality_id':people['quality']['id'],'commerce_id':people['biz']['id']}
    def attempt():return mutation(cs['pm'],'POST',procbase(p)+'/orders',body)
    assert attempt().status_code==409
    ok(act(change,'revise',replacement=payload));publish(change);acknowledge(change)
    assert attempt().status_code==409
    dispose(change);ok(attempt())

def test_noncontinue_disposition_keeps_purchase_facts_and_blocks_execution(change):
    publish(change);acknowledge(change);flow,_,o,_=change
    target=next(t for t in get(change)['current']['body']['targets'] if t['key'].startswith('procurement:'))
    ok(act(change,'plan',target_key=target['key'],decision='cancel',reason='登记外部取消处理依据，不自动撤销真实订单'))
    f=ok(upload(change,'purchase','execution'));ok(act(change,'execute','purchase',target_key=target['key'],reason='供应商处理证据已核对',file_ids=[f['id']]));ok(act(change,'verify',target_key=target['key']))
    assert proc_get(flow)['state']=='pm_review' and proc_get(flow)['result'] is not None
    assert proc_act(flow,o,'approve_purchase','pm').status_code==409

def test_concurrent_professional_confirmation_has_one_cas_winner(change):
    from concurrent.futures import ThreadPoolExecutor
    flow,c,_,_=change;(_,_,p,cs,_),_=flow;revision=get(change)['revision']
    def send(pair):
        cat,who=pair;return mutation(cs[who],'POST',base(p)+'/'+c['id']+'/actions',{'revision':revision,'action':'impact','category':cat,'has_impact':False,'reason':'并发专业核对'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(send,[('technical','design'),('cost','biz')]))
    assert sorted(statuses)==[200,409] and len(get(change)['draft']['impacts'])==1

def test_publish_transaction_failure_rolls_back_version_and_notifications(change,monkeypatch):
    from app import change_service
    flow,c,_,_=change;(app,_,_,_,_),_=flow
    impacts(change);f=ok(upload(change));ok(act(change,'approval',approval_no='APPROVED',reason='已取得脱敏依据',file_ids=[f['id']]))
    original=change_service.record
    def fail_after_write(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('transaction fault')
    monkeypatch.setattr(change_service,'record',fail_after_write)
    with pytest.raises(RuntimeError):act(change,'publish',recipient_ids=get(change)['required_recipient_ids'])
    with app.state.store.transaction() as db:
        assert db.get(ChangeCase,c['id']).current_version_id is None
        assert not db.scalars(select(ChangeVersion).where(ChangeVersion.case_id==c['id'])).all()

def test_emergency_and_external_wait_never_substitute_approval(change):
    flow,_,_,payload=change;(app,_,p,cs,_),_=flow
    emergency=ok(mutation(cs['pm'],'POST',base(p),payload|{'emergency':True,'title':'紧急变更仅登记'}))
    with app.state.store.transaction(write=True) as db:
        c=db.get(ChangeCase,emergency['id']);c.draft=c.draft|{'emergency_due_at':'2020-01-01T00:00:00+00:00'}
        from app.handoff_service import reconcile
        reconcile(db,p['id'])
    r=mutation(cs['pm'],'POST',base(p)+'/'+emergency['id']+'/actions',{'revision':1,'action':'publish','recipient_ids':[]});assert r.status_code==409
    ok(act(change,'wait',waiting='external_approval',reason='等待既有外部审批'))
    assert get(change)['draft']['waiting']=='external_approval'
    assert act(change,'close').status_code==409


def test_latest_change_cannot_be_bypassed_by_older_completed_case(change):
    from app.change_service import can_start
    from app.handoff_models import Version
    flow,original,_,payload=change;(app,_,p,cs,_),_=flow
    publish(change);acknowledge(change);dispose(change)
    with app.state.store.transaction() as db:assert can_start(db,p['id'],db.get(Version,payload['new_version_id']))
    second=ok(mutation(cs['pm'],'POST',base(p),payload|{'title':'后续范围复核'}))
    another=(flow,second,change[2],payload)
    publish(another)
    with app.state.store.transaction() as db:assert not can_start(db,p['id'],db.get(Version,payload['new_version_id']))


def test_missing_approval_original_cannot_authorize_old_execution(change):
    from pathlib import Path
    from app.change_models import ChangeFile
    publish(change);acknowledge(change);dispose(change);flow,_,o,_=change
    (app,_,_,_,_),_=flow
    with app.state.store.transaction() as db:
        fid=get(change)['current']['body']['approval']['file_ids'][0];Path(db.get(ChangeFile,fid).path).unlink()
    assert proc_act(flow,o,'approve_purchase','pm').status_code==409
