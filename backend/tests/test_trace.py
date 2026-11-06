import uuid
from datetime import datetime,timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from app.trace_models import TraceFile
from test_procurement import flow,ok
from test_handoff import chain
from test_pilot_foundation import add_account,grant,login,mutation
@pytest.fixture
def trace(flow):
 env,scheme=flow;app,admin,p,cs,people=env
 for who,r in [('factory','工厂'),('site','现场')]:
  person=add_account(admin,who);people[who]=person;ok(grant(admin,p,person,[r]));c=TestClient(app,base_url='http://127.0.0.1');login(c,who);cs[who]=c
 yield {'env':env,'scheme':scheme}
def base(t):return '/projects/'+t['env'][2]['id']+'/trace'
def post(t,who,path,b,key=None):return mutation(t['env'][3][who],'POST',base(t)+path,b,key)
def board(t):
 r=t['env'][3]['pm'].get('/api'+base(t)+'/board');assert r.status_code==200,r.text;return r.json()
def get(t):return next(s for s in board(t)['spools'] if s['id']==t['spool']['id'])
def prepare(t,welding=True,pressure=True):
 p=t['env'][4];t['template']=ok(post(t,'quality','/templates',{'name':'合成模板','scope':'仅QA','welding':welding,'pressure':pressure,'basis':'质量负责人确认合成工序适用，不代表实际工艺批准'}));t['order']=ok(post(t,'pm','/orders',{'code':'FAB-1','version_id':t['scheme']['versions'][0]['id'],'factory_id':p['factory']['id'],'site_id':p['site']['id'],'quality_id':p['quality']['id']}));t['spool']=ok(post(t,'factory','/spools',{'code':'SP-1','order_id':t['order']['id'],'template_id':t['template']['id']}));return t
def action(t,name,who='factory',**kw):return post(t,who,'/spools/'+get(t)['id']+'/actions',{'revision':get(t)['revision'],'action':name,**kw})
def upload(t,who='factory'):
 c=t['env'][3][who];r=c.post('/api'+base(t)+'/spools/'+get(t)['id']+'/files',files={'file':('evidence.md',b'synthetic trace evidence','text/plain')},headers={'X-CSRF-Token':c.get('/api/session').json()['csrf'],'X-Idempotency-Key':uuid.uuid4().hex});return ok(r)['id']
def record(t,kind,data,who='factory',**kw):return post(t,who,'/spools/'+get(t)['id']+'/records',{'revision':get(t)['revision'],'kind':kind,'data':data,'occurred_at':datetime.now(timezone.utc).isoformat(),**kw})
def fabricate(t):
 prepare(t);ok(record(t,'material',{'batch':'MAT-1'},file_ids=[upload(t)]));ok(action(t,'start'));ok(record(t,'weld',{'weld_code':'W-1','welder_code':'QUAL-1','consumable_batch':'WIRE-1','equipment':'EQ-1'}));ok(record(t,'fabrication',{'equipment':'EQ-1','description':'合成预制完成'}));ok(action(t,'submit_inspection'));return t
def inspect(t,passed=True):return action(t,'inspect','quality',passed=passed,reason='合成质量核对',file_ids=[upload(t,'quality')],weld_ids=[w['id'] for w in get(t)['welds']])
def ship(t):return action(t,'ship',location='合成库位',reference='SYN-SHIP',occurred_at=datetime.now(timezone.utc).isoformat())
def install(t):return action(t,'install','site',location='合成位置',reference='SYN-INSTALL',occurred_at=datetime.now(timezone.utc).isoformat())
def test_stage_report_repair_reinspection_gates(trace):
 prepare(trace);assert action(trace,'start').status_code==409;assert record(trace,'material',{'batch':'M'}).status_code==422
 ok(record(trace,'material',{'batch':'M'},file_ids=[upload(trace)]));ok(action(trace,'start'));assert record(trace,'weld',{'weld_code':'W1'}).status_code==422
 ok(record(trace,'weld',{'weld_code':'W1','welder_code':'Q','consumable_batch':'B','equipment':'E'}));ok(record(trace,'fabrication',{'equipment':'E','description':'完成'}));ok(action(trace,'submit_inspection'))
 assert action(trace,'inspect','quality',passed=True,reason='缺报告',weld_ids=[w['id'] for w in get(trace)['welds']]).status_code==422
 ok(inspect(trace,False));assert ship(trace).status_code==409;assert action(trace,'submit_inspection').status_code==409
 ok(record(trace,'repair',{'description':'返修'},file_ids=[upload(trace)]));ok(action(trace,'submit_inspection'));ok(inspect(trace));ok(ship(trace));assert len([r for r in get(trace)['records'] if r['kind']=='inspection'])==2

def test_only_assigned_quality_can_sign(trace):
 fabricate(trace);assert action(trace,'inspect','factory',passed=True,reason='越权',file_ids=[upload(trace)]).status_code==403
 assert post(trace,'factory','/templates',{'name':'任意免检','scope':'X','welding':False,'pressure':False,'basis':'X'}).status_code==403
 assert action(trace,'ship','site').status_code==403

def test_pressure_failure_requires_repair_new_report_and_quality(trace):
 fabricate(trace);ok(inspect(trace));ok(ship(trace));ok(install(trace));assert action(trace,'complete','quality',reason='缺试压').status_code==409
 ok(record(trace,'pressure',{'equipment':'P1','description':'合成试压'},'site',file_ids=[upload(trace,'site')]))
 assert action(trace,'confirm_pressure','quality',passed=True,reason='缺报告').status_code==422
 ok(action(trace,'confirm_pressure','quality',passed=False,reason='不合格',file_ids=[upload(trace,'quality')]))
 assert action(trace,'confirm_pressure','quality',passed=True,reason='直接改判',file_ids=[upload(trace,'quality')]).status_code==409
 ok(record(trace,'repair',{'description':'试压返修'},'site',file_ids=[upload(trace,'site')]));ok(record(trace,'pressure',{'equipment':'P2','description':'合成复压'},'site',file_ids=[upload(trace,'site')]))
 assert action(trace,'confirm_pressure','quality',passed=True,reason='尚未复核',file_ids=[upload(trace,'quality')]).status_code==409
 ok(inspect(trace))
 ok(action(trace,'confirm_pressure','quality',passed=True,reason='复压合格',file_ids=[upload(trace,'quality')]));ok(action(trace,'complete','quality',reason='核对齐全'));assert board(trace)['metrics']['completed_rate']==1
 ok(inspect(trace));ok(action(trace,'complete','quality',reason='复核原件及既有试压仍有效'))

@pytest.mark.parametrize('welding',[False,True])
def test_quality_template_nonapplicable_and_denominators(trace,welding):
 prepare(trace,welding,False);assert board(trace)['metrics']['completed_rate'] is None
 ok(record(trace,'material',{'batch':'B'},file_ids=[upload(trace)]));ok(action(trace,'start'))
 if welding:ok(record(trace,'weld',{'weld_code':'W1','welder_code':'Q','consumable_batch':'B','equipment':'E'}))
 else:assert record(trace,'weld',{'weld_code':'W1','welder_code':'Q','consumable_batch':'B','equipment':'E'}).status_code==409
 ok(record(trace,'fabrication',{'equipment':'E','description':'完成'}));ok(action(trace,'submit_inspection'));ok(inspect(trace));ok(ship(trace));ok(install(trace));ok(action(trace,'complete','quality',reason='适用履历齐全'));assert board(trace)['metrics']['completed_total']==1

def test_duplicate_codes_label_reprint_qr_auth_and_scrap(trace):
 prepare(trace);payload={'code':'SP-1','order_id':trace['order']['id'],'template_id':trace['template']['id']};assert post(trace,'factory','/spools',payload).status_code==409
 a=ok(action(trace,'label'));b=ok(action(trace,'label'));assert a['id']==b['id'] and a['locator']==b['locator']
 cs=trace['env'][3];url='/api'+base(trace)+'/spools/'+get(trace)['id']+'/qr';assert cs['factory'].get(url).headers['content-type'].startswith('image/svg+xml');assert cs['outsider'].get(url).status_code==404
 assert TestClient(trace['env'][0],base_url='http://127.0.0.1').get(url).status_code==401
 assert cs['outsider'].get('/api/spool-locator/'+get(trace)['id']).status_code==404
 ok(action(trace,'scrap','quality',reason='合成报废'));assert post(trace,'factory','/spools',payload).status_code==409
 assert board(trace)['metrics']['scrapped']==1 and board(trace)['metrics']['completed_total']==0

def test_append_correction_invalidates_old_quality_and_originals_immutable(trace):
 fabricate(trace);ok(inspect(trace));old=next(r for r in get(trace)['records'] if r['kind']=='material');before=len(get(trace)['records'])
 ok(record(trace,'material',{'batch':'NEW'},file_ids=[upload(trace)],corrects_id=old['id'],correction_reason='合成批次更正'))
 assert get(trace)['state']=='inspection' and len(get(trace)['records'])==before+1 and any(r['data'].get('batch')=='MAT-1' for r in get(trace)['records']);assert ship(trace).status_code==409;ok(inspect(trace));ok(ship(trace))
 with pytest.raises(DatabaseError):
  with trace['env'][0].state.store.transaction(write=True) as db:db.execute(text('UPDATE trace_records SET source="automatic"'))

def test_split_merge_preserves_lineage_and_cas(trace):
 prepare(trace);s=get(trace);body={'parents':[{'id':s['id'],'revision':s['revision']}],'codes':['SP-A','SP-B'],'reason':'合成拆分'};out=ok(post(trace,'pm','/reshape',body));assert get(trace)['state']=='retired'
 children=[s for s in board(trace)['spools'] if s['id'] in out['ids']];assert len(children)==2 and all(s['parents']==[trace['spool']['id']] and not s['records'] for s in children)
 ok(post(trace,'pm','/reshape',{'parents':[{'id':s['id'],'revision':s['revision']} for s in children],'codes':['SP-C'],'reason':'合成合并'}));assert board(trace)['metrics']['retired']==3;assert post(trace,'pm','/reshape',body).status_code==409

def test_report_hash_and_foreign_spool_scope(trace):
 fabricate(trace);f=upload(trace,'quality');sid=get(trace)['id'];other=ok(post(trace,'factory','/spools',{'code':'SP-2','order_id':trace['order']['id'],'template_id':trace['template']['id']}));trace['spool']=other
 assert record(trace,'material',{'batch':'X'},file_ids=[f]).status_code==422
 trace['spool']={'id':sid}
 with trace['env'][0].state.store.transaction() as db:
  from pathlib import Path
  Path(db.get(TraceFile,f).path).write_bytes(b'tampered')
 assert action(trace,'inspect','quality',passed=True,reason='tampered',file_ids=[f],weld_ids=[w['id'] for w in get(trace)['welds']]).status_code==409

def test_concurrent_and_durable_idempotency(trace):
 from concurrent.futures import ThreadPoolExecutor
 prepare(trace);s=get(trace);body={'revision':s['revision'],'kind':'material','data':{'batch':'B'},'file_ids':[upload(trace)],'occurred_at':datetime.now(timezone.utc).isoformat()};path='/spools/'+s['id']+'/records'
 with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(lambda _:post(trace,'factory',path,body).status_code,range(2)))
 assert sorted(codes)==[200,409] and len(get(trace)['records'])==1
 body={'revision':get(trace)['revision'],'action':'start'};path='/spools/'+s['id']+'/actions';r=post(trace,'factory',path,body,'trace-retry');ok(r);assert post(trace,'factory',path,body,'trace-retry').json()==r.json()


def test_new_formal_source_includes_real_spool_and_blocks_old_execution(trace):
 from test_handoff import post as hp,path as hpath
 prepare(trace);app,_,p,cs,_=trace['env'];docs=cs['pm'].get('/api'+hpath(p,'/board')).json()['documents'];d=next(x for x in docs if x['kind']=='requirement');old=d['versions'][0]
 d=ok(hp(cs['market'],p,'/documents/'+d['id']+'/revise',{'revision':d['revision']}));d=ok(mutation(cs['market'],'PATCH',hpath(p,'/documents/'+d['id']),{'revision':d['revision'],'body':old['body']|{'summary':'变更管段来源'}}));d=ok(hp(cs['biz'],p,'/documents/'+d['id']+'/publish',{'revision':d['revision'],'recipient_ids':[trace['env'][4]['design']['id']],'diff_summary':'现场调整'}))
 path='/projects/'+p['id']+'/changes';case=ok(mutation(cs['pm'],'POST',path,{'title':'影响实际管段','reason':'核对在制对象','old_version_id':old['id'],'new_version_id':d['versions'][0]['id']}));c=next(c for c in cs['pm'].get('/api'+path+'/board').json()['cases'] if c['id']==case['id']);assert any(t['key']=='spool:'+get(trace)['id'] for t in c['draft']['targets']);assert action(trace,'start').status_code==409

def test_spool_creation_and_locator_do_not_allow_cross_project(trace):
 from test_pilot_foundation import add_project
 prepare(trace);_,admin,_,cs,_=trace['env'];other=add_project(admin,'TRACE-OTHER');path='/projects/'+other['id']+'/trace/spools';payload={'code':'OTHER','order_id':trace['order']['id'],'template_id':trace['template']['id']};assert mutation(admin,'POST',path,payload).status_code in {403,404}

def test_record_transaction_rollback_keeps_no_weld_or_record(trace,monkeypatch):
 from app import trace_service
 prepare(trace);ok(record(trace,'material',{'batch':'M'},file_ids=[upload(trace)]));ok(action(trace,'start'));before=get(trace)
 def fault(*args,**kwargs):raise RuntimeError('after write fault')
 monkeypatch.setattr(trace_service,'event',fault)
 with pytest.raises(RuntimeError):record(trace,'weld',{'weld_code':'W1','welder_code':'Q1','consumable_batch':'B1','equipment':'E1'})
 after=get(trace);assert after['revision']==before['revision'] and after['records']==before['records'] and not after['welds']


def test_actual_template_import_requires_matching_original_and_manual_source_stays_distinct(trace):
 import json
 prepare(trace);c=trace['env'][3]['factory'];data={'batch':'IMPORTED-BATCH'};when=datetime.now(timezone.utc).isoformat();raw=json.dumps({'kind':'material','data':data,'occurred_at':when}).encode();r=c.post('/api'+base(trace)+'/spools/'+get(trace)['id']+'/files',files={'file':('actual-template.json',raw,'application/json')},headers={'X-CSRF-Token':c.get('/api/session').json()['csrf'],'X-Idempotency-Key':uuid.uuid4().hex});fid=ok(r)['id'];body={'revision':get(trace)['revision'],'kind':'material','data':data,'occurred_at':when,'source':'template_import','file_ids':[fid]};path='/spools/'+get(trace)['id']+'/records'
 assert post(trace,'factory',path,body|{'data':{'batch':'tampered'}}).status_code==422
 ok(post(trace,'factory',path,body));assert get(trace)['records'][0]['source']=='template_import'
 assert post(trace,'factory',path,body|{'source':'automatic'}).status_code==422

def test_staff_qualification_code_hidden_from_nonprocessing_project_role(trace):
 fabricate(trace);cs=trace['env'][3];ordinary=cs['biz'].get('/api'+base(trace)+'/board');assert ordinary.status_code==200 and 'QUAL-1' not in ordinary.text
 assert 'QUAL-1' in cs['quality'].get('/api'+base(trace)+'/board').text

def test_weld_coverage_and_unsafe_files_are_rejected(trace):
 fabricate(trace);assert action(trace,'inspect','quality',passed=True,reason='未覆盖焊缝',file_ids=[upload(trace,'quality')],weld_ids=[]).status_code==422
 c=trace['env'][3]['factory'];url='/api'+base(trace)+'/spools/'+get(trace)['id']+'/files';hdr={'X-CSRF-Token':c.get('/api/session').json()['csrf'],'X-Idempotency-Key':uuid.uuid4().hex}
 assert c.post(url,files={'file':('../unsafe.md',b'no','text/plain')},headers=hdr).status_code==422
 assert c.post(url,files={'file':('fake.pdf',b'not pdf','application/pdf')},headers=hdr|{'X-Idempotency-Key':uuid.uuid4().hex}).status_code==422


def test_revoked_project_cannot_replay_prior_mutation_result(trace):
 prepare(trace);s=get(trace);body={'revision':s['revision'],'action':'label'};path='/spools/'+s['id']+'/actions';ok(post(trace,'factory',path,body,'trace-revoke-replay'))
 _,admin,p,_,people=trace['env'];ok(grant(admin,p,people['factory'],['工厂'],revision=1,active=False))
 assert post(trace,'factory',path,body,'trace-revoke-replay').status_code==404


def test_assurance_quality_exception_does_not_waive_shipping_gate(trace):
 prepare(trace);cs=trace['env'][3];pid=trace['env'][2]['id'];base26='/projects/'+pid+'/assurance'
 assert not ok(cs['pm'].get('/api'+base26+'/board'))['exceptions']
 ok(record(trace,'material',{'batch':'ASSURANCE'},file_ids=[upload(trace)]));ok(action(trace,'start'));ok(record(trace,'weld',{'weld_code':'W-A','welder_code':'Q-A','consumable_batch':'C-A','equipment':'E-A'}));ok(record(trace,'fabrication',{'equipment':'E-A','description':'完成'}));ok(action(trace,'submit_inspection'));ok(inspect(trace,False))
 exceptions=ok(cs['pm'].get('/api'+base26+'/board'))['exceptions'];e=next(x for x in exceptions if x['rule_id']=='trace.nonconformance');c=cs['pm'];response=c.post('/api'+base26+'/exceptions/'+e['id']+'/files',files={'file':('synthetic.md',b'Approved exception reminder only','text/plain')},headers={'X-CSRF-Token':c.get('/api/session').json()['csrf'],'X-Idempotency-Key':uuid.uuid4().hex});fid=ok(response)['id']
 from datetime import timedelta
 ok(mutation(c,'POST',base26+'/exceptions/'+e['id']+'/actions',{'revision':e['revision'],'action':'waive','reason':'只豁免提醒，不放行质量','approval_no':'SYN-A','until':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),'file_ids':[fid]}))
 assert ship(trace).status_code==409 and get(trace)['state']=='rework'
