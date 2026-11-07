"""Real SQL/auth/parser/graph boundaries for the unified project adapter."""
import io,hashlib
import pytest
from sqlalchemy import select
from test_pilot_foundation import env,add_project,add_account,grant,user_client,mutation
from app.knowledge_api import run_knowledge_job
from app.knowledge_models import KnowledgeDocument,RuleRun

def ok(r):assert r.status_code==200,r.text;return r.json()
@pytest.fixture
def knowledge(env):
    app,admin=env;p=add_project(admin);person=add_account(admin,'reader');ok(grant(admin,p,person,['采购']));reader=user_client(app,'reader')
    base='/projects/'+p['id']+'/knowledge';library=ok(mutation(admin,'POST',base+'/libraries',{'name':'项目资料','readers':[person['id']]}))
    yield app,admin,p,person,reader,library,base+'/libraries/'+library['id']
    reader.close()

def upload(k,key='knowledge-upload',name='policy.md',raw=b'# Policy\n\nMaterials require quality review.'):
    app,admin,_,_,_,_,base=k
    c=admin.get('/api/session').json()['csrf']
    return admin.post('/api'+base+'/documents',files={'file':(name,raw,'text/plain')},headers={'X-CSRF-Token':c,'X-Idempotency-Key':key})
def publish(k):
    app,admin,_,_,_,_,base=k;d=ok(upload(k));assert run_knowledge_job(app.state.store)
    d=ok(admin.get('/api'+base+'/documents/'+d['id']));return ok(mutation(admin,'POST',base+'/documents/'+d['id']+'/actions',{'revision':d['revision'],'action':'publish'}))
def graph(text='核对：{{input}}'):
    return {'name':'合成规则应用','nodes':[{'id':n,'kind':k,'label':n,'config':c} for n,k,c in [('start','start',{}),('text','template',{'template':text}),('out','output',{'template':'{{previous.output}}'})]],'edges':[{'id':'s-t','source':'start','target':'text'},{'id':'t-o','source':'text','target':'out'}]}

def test_upload_parse_review_publish_original_and_search(knowledge):
    app,admin,_,_,reader,_,base=knowledge;d=ok(upload(knowledge))
    assert reader.get('/api'+base+'/documents/'+d['id']).status_code==404
    assert reader.get('/api'+base+'/documents/'+d['id']+'/original').status_code==404
    assert ok(mutation(reader,'POST',base+'/search',{'query':'quality'}))['results']==[]
    assert run_knowledge_job(app.state.store)
    d=ok(admin.get('/api'+base+'/documents/'+d['id']));assert d['state']=='review' and d['chunks']
    d=ok(mutation(admin,'POST',base+'/documents/'+d['id']+'/actions',{'revision':d['revision'],'action':'publish'}))
    r=ok(mutation(reader,'POST',base+'/search',{'query':'quality'}));assert r['results'] and not r['model_enabled']
    raw=reader.get(r['results'][0]['original_url']);assert hashlib.sha256(raw.content).hexdigest()==d['sha256']
    d=ok(mutation(admin,'POST',base+'/documents/'+d['id']+'/actions',{'revision':d['revision'],'action':'withdraw'}))
    assert not ok(mutation(reader,'POST',base+'/search',{'query':'quality'}))['results']
    assert reader.get('/api'+base+'/documents/'+d['id']+'/original').status_code==404

def test_cross_project_acl_revoke_and_saved_result_recheck(knowledge):
    app,admin,p,person,reader,lib,base=knowledge;d=publish(knowledge)
    other=add_project(admin,'P-OTHER');cross=base.replace(p['id'],other['id'])
    assert admin.get('/api'+cross+'/documents/'+d['id']).status_code==404
    l=ok(mutation(admin,'PUT',base,{'name':lib['name'],'readers':[],'restricted':True,'revision':lib['revision']}))
    assert reader.get('/api'+base+'/documents').status_code==404
    assert reader.get('/api'+base+'/documents/'+d['id']+'/original').status_code==404
    ok(grant(admin,p,{'id':lib['owner_id']},['管理员'],revision=1,active=False))
    assert admin.get('/api/requests/knowledge-upload').status_code==404
    assert upload(knowledge).status_code==404

def test_upload_idempotency_replay_and_content_conflict(knowledge):
    first=ok(upload(knowledge));again=ok(upload(knowledge));assert first==again
    assert upload(knowledge,raw=b'other bytes').status_code==409
    admin=knowledge[1];base=knowledge[-1];assert ok(admin.get('/api'+base+'/documents'))['total']==1
    recovered=ok(admin.get('/api/requests/knowledge-upload'));assert recovered['result']['id']==first['id']

def test_bad_files_refused_and_original_tamper_blocks_publish(knowledge):
    assert upload(knowledge,name='../x.md').status_code==422
    assert upload(knowledge,name='fake.pdf').status_code==422
    assert upload(knowledge,name='fake.xlsx').status_code==422
    assert upload(knowledge,raw=b'\x00binary').status_code==422
    d=ok(upload(knowledge));app,admin,_,_,_,_,base=knowledge;run_knowledge_job(app.state.store)
    from pathlib import Path
    with app.state.store.transaction() as db:Path(db.get(KnowledgeDocument,d['id']).path).write_bytes(b'changed')
    d=ok(admin.get('/api'+base+'/documents/'+d['id']));assert mutation(admin,'POST',base+'/documents/'+d['id']+'/actions',{'revision':d['revision'],'action':'publish'}).status_code==409

def test_rule_eval_gate_draft_publication_and_idempotent_run(knowledge):
    app,admin,_,_,reader,_,base=knowledge
    a=ok(mutation(admin,'POST',base+'/applications',{'definition':graph()}));path=base+'/applications/'+a['id']
    assert mutation(reader,'POST',path+'/run',{'input':'材料'}).status_code==409
    assert mutation(reader,'POST',path+'/run',{'input':'材料','mode':'draft'}).status_code==403
    assert mutation(admin,'POST',path+'/publish',{'revision':1,'cases':[{'input':'材料','expectContains':'不存在'}]}).status_code==422
    ok(mutation(admin,'POST',path+'/publish',{'revision':1,'cases':[{'input':'材料','expectContains':'核对'}]}))
    first=ok(mutation(reader,'POST',path+'/run',{'input':'材料'},key='knowledge-rule-run'));assert first['output']=='核对：材料' and first['tokens'] is None
    assert ok(mutation(reader,'POST',path+'/run',{'input':'材料'},key='knowledge-rule-run'))==first
    ok(mutation(admin,'PUT',path,{'definition':graph('新版：{{input}}'),'revision':1}))
    assert ok(mutation(reader,'POST',path+'/run',{'input':'材料'}))['output']=='核对：材料'
    assert ok(mutation(admin,'POST',path+'/run',{'input':'材料','mode':'draft'}))['output']=='新版：材料'
    with app.state.store.transaction() as db:assert len(list(db.scalars(select(RuleRun))))==3

def test_model_nodes_rejected_and_run_history_revoked(knowledge):
    app,admin,p,person,reader,lib,base=knowledge;g=graph();g['nodes'][1]['kind']='llm';assert mutation(admin,'POST',base+'/applications',{'definition':g}).status_code==409
    a=ok(mutation(admin,'POST',base+'/applications',{'definition':graph()}));path=base+'/applications/'+a['id']
    ok(mutation(admin,'POST',path+'/publish',{'revision':1,'cases':[{'input':'材料','expectContains':'核对'}]}))
    ok(mutation(reader,'POST',path+'/run',{'input':'材料'},key='reader-history-run'))
    assert ok(reader.get('/api'+base+'/runs')) and not ok(admin.get('/api'+base+'/runs'))
    ok(mutation(admin,'PUT',base,{'name':lib['name'],'readers':[],'restricted':True,'revision':lib['revision']}))
    assert reader.get('/api'+base+'/runs').status_code==404
    assert reader.get('/api/requests/reader-history-run').status_code==404

def test_queued_task_can_recover_expired_parse_lease(knowledge):
    from app.pilot_models import utcnow
    app,admin,_,_,_,_,base=knowledge;d=ok(upload(knowledge))
    with app.state.store.transaction(write=True) as db:
        row=db.get(KnowledgeDocument,d['id']);row.state='parsing';row.attempts=1;row.lease_until='2000-01-01T00:00:00+00:00'
    assert run_knowledge_job(app.state.store)
    d=ok(admin.get('/api'+base+'/documents/'+d['id']));assert d['state']=='review'

def test_rule_published_rollback_and_condition_branch(knowledge):
    _,admin,_,_,reader,_,base=knowledge
    a=ok(mutation(admin,'POST',base+'/applications',{'definition':graph()}));path=base+'/applications/'+a['id']
    ok(mutation(admin,'POST',path+'/publish',{'revision':1,'cases':[{'input':'材料','expectContains':'核对'}]}))
    ok(mutation(admin,'PUT',path,{'definition':graph('新版：{{input}}'),'revision':1}))
    ok(mutation(admin,'POST',path+'/publish',{'revision':2,'cases':[{'input':'材料','expectContains':'新版'}]}))
    assert ok(mutation(reader,'POST',path+'/run',{'input':'材料'}))['output']=='新版：材料'
    ok(mutation(admin,'POST',path+'/rollback',{'revision':2,'target_revision':1}))
    assert ok(mutation(reader,'POST',path+'/run',{'input':'材料'}))['output']=='核对：材料'
    assert ok(mutation(admin,'POST',path+'/run',{'input':'材料','mode':'draft'}))['output']=='新版：材料'
    from app.applications import scenario_template
    # Build the original rule DSL's condition branches; no provider resources.
    g={'name':'分流','nodes':[{'id':n,'kind':k,'label':n,'config':c} for n,k,c in [('start','start',{}),('gate','condition',{'source':'{{input}}','operator':'contains','value':'到货'}),('yes','template',{'template':'质量验收'}),('no','template',{'template':'继续核对'}),('out','output',{'template':'{{previous.output}}'})]],'edges':[{'id':'s-g','source':'start','target':'gate'},{'id':'g-y','source':'gate','target':'yes','sourceHandle':'true'},{'id':'g-n','source':'gate','target':'no','sourceHandle':'false'},{'id':'y-o','source':'yes','target':'out'},{'id':'n-o','source':'no','target':'out'}]}
    a=ok(mutation(admin,'POST',base+'/applications',{'definition':g}));path=base+'/applications/'+a['id']
    ok(mutation(admin,'POST',path+'/publish',{'revision':1,'cases':[{'input':'已到货','expectContains':'质量验收'},{'input':'采购','expectContains':'继续核对'}]}))
    assert ok(mutation(reader,'POST',path+'/run',{'input':'已到货'}))['output']=='质量验收'
    assert ok(mutation(reader,'POST',path+'/run',{'input':'采购'}))['output']=='继续核对'

def test_knowledge_location_validates_shared_scope(knowledge):
    _,admin,p,_,reader,lib,base=knowledge
    path=f'/api/projects/{p["id"]}/workspace/locate?section=knowledge&kind=library&object_id={lib["id"]}'
    assert ok(reader.get(path))['title']==lib['name']
    ok(mutation(admin,'PUT',base,{'name':lib['name'],'readers':[],'restricted':True,'revision':lib['revision']}))
    assert reader.get(path).status_code==404

def test_full_bundle_restores_knowledge_originals_and_rule_runs(knowledge,tmp_path):
    from app.data_bundle import backup,restore
    from pathlib import Path
    import sqlite3
    app,admin,_,_,reader,_,base=knowledge;d=publish(knowledge)
    a=ok(mutation(admin,'POST',base+'/applications',{'definition':graph()}));path=base+'/applications/'+a['id']
    ok(mutation(admin,'POST',path+'/publish',{'revision':1,'cases':[{'input':'材料','expectContains':'核对'}]}))
    r=ok(mutation(reader,'POST',path+'/run',{'input':'材料'}))
    folder=Path(app.state.store.engine.url.database).parent;archive=tmp_path/'backup.zip';m=backup(folder,archive)
    assert m['database']['counts']['knowledge_documents']==1 and m['database']['counts']['knowledge_runs']==1
    dest=tmp_path/'restored';after=restore(archive,dest);assert after['fingerprints']==m['database']['fingerprints']
    with sqlite3.connect(dest/'pilot.db') as db:
        new_path=db.execute('select path from knowledge_documents').fetchone()[0]
        assert Path(new_path).parent==dest/'knowledge-originals'
        assert hashlib.sha256(Path(new_path).read_bytes()).hexdigest()==d['sha256']
        assert db.execute('select count(*) from pilot_sessions').fetchone()[0]==0

def test_reserved_model_interfaces_are_scoped_and_do_not_forge_answers(knowledge):
    _,admin,p,_,reader,lib,base=knowledge
    r=mutation(reader,'POST',base+'/retrieve',{'query':'到货'})
    assert r.status_code==503 and r.json()['error']['code']=='MODEL_NOT_CONFIGURED'
    r=mutation(reader,'POST',base+'/chat/stream',{'query':'到货'})
    assert r.status_code==200 and 'event: error' in r.text and 'MODEL_NOT_CONFIGURED' in r.text and 'event: token' not in r.text
    ok(mutation(admin,'PUT',base,{'name':lib['name'],'readers':[],'restricted':True,'revision':lib['revision']}))
    assert mutation(reader,'POST',base+'/retrieve',{'query':'到货'}).status_code==404
    assert mutation(reader,'POST',base+'/chat/stream',{'query':'到货'}).status_code==404

def test_task_progress_is_owner_only_and_actions_match_state(knowledge):
    app,admin,_,_,reader,_,base=knowledge
    d=ok(upload(knowledge));progress=d['processing']
    assert progress['attempts']==0 and progress['max_attempts']==3
    assert not progress['can_retry'] and not progress['can_publish']
    assert '重复上传' in d['status_hint']
    assert run_knowledge_job(app.state.store)
    d=ok(admin.get('/api'+base+'/documents/'+d['id']))
    assert d['processing']['attempts']==1 and d['processing']['can_publish']
    d=ok(mutation(admin,'POST',base+'/documents/'+d['id']+'/actions',{'revision':d['revision'],'action':'publish'}))
    assert not d['processing']['can_publish']
    shared=ok(reader.get('/api'+base+'/documents/'+d['id']))
    assert 'processing' not in shared and 'AI' in shared['status_hint']
    assert 'processing' not in ok(reader.get('/api'+base+'/documents'))['items'][0]
    assert 'processing' in ok(admin.get('/api'+base+'/documents'))['items'][0]


def test_expired_lease_progress_and_attempt_limit_retain_original(knowledge):
    app,admin,_,_,_,_,base=knowledge;d=ok(upload(knowledge))
    with app.state.store.transaction(write=True) as db:
        row=db.get(KnowledgeDocument,d['id']);row.state='parsing';row.attempts=3;row.lease_until='2000-01-01T00:00:00+00:00'
    path='/api'+base+'/documents/'+d['id']
    assert ok(admin.get(path))['processing']['waiting_for_recovery']
    assert run_knowledge_job(app.state.store)
    d=ok(admin.get(path));assert d['state']=='failed' and d['processing']['can_retry']
    assert d['processing']['lease_expires_at'] is None
    raw=admin.get(path+'/original');assert hashlib.sha256(raw.content).hexdigest()==d['sha256']
    retried=ok(mutation(admin,'POST',base+'/documents/'+d['id']+'/actions',{'revision':d['revision'],'action':'retry'}))
    assert retried['state']=='queued' and retried['processing']['attempts']==0
    assert run_knowledge_job(app.state.store)
    assert ok(admin.get(path))['state']=='review'
    assert ok(admin.get('/api'+base+'/documents'))['total']==1
