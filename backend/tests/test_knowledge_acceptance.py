"""Frozen acceptance inputs are independent of the implementation under test."""
import hashlib,json
from pathlib import Path
import pytest
from test_pilot_foundation import env,add_project,grant,mutation
from test_unified_knowledge import knowledge,upload,graph,ok
from app.knowledge_api import run_knowledge_job
FIXTURE=Path(__file__).parent/'fixtures/knowledge_acceptance_v1.json'
SPECS=json.loads(FIXTURE.read_text())
SHA=hashlib.sha256(FIXTURE.read_bytes()).hexdigest()


def record(record_property,spec,category,observed):
    record_property('case_id',spec['id']);record_property('category',category)
    record_property('fixture_sha256',SHA);record_property('observed',json.dumps(observed,ensure_ascii=False))


def seed(k,name,text,publish=True):
    app,admin,_,_,_,_,base=k
    d=ok(upload(k,key='frozen-'+name,name=name,raw=text.encode()))
    if publish:
        assert run_knowledge_job(app.state.store)
        d=ok(admin.get('/api'+base+'/documents/'+d['id']))
        d=ok(mutation(admin,'POST',base+'/documents/'+d['id']+'/actions',{'revision':d['revision'],'action':'publish'}))
    return d


@pytest.mark.parametrize('spec',SPECS['retrieval'],ids=lambda s:s['id'])
def test_frozen_retrieval(knowledge,spec,record_property):
    app,admin,project,person,reader,lib,base=knowledge
    scenario=spec['scenario'];k=knowledge
    if scenario=='private':
        private=ok(mutation(admin,'POST',base.rsplit('/libraries/',1)[0]+'/libraries',{'name':'固定私有空间','readers':[]}))
        base=base.rsplit('/',1)[0]+'/'+private['id'];k=(*knowledge[:-1],base)
    text={'long':'长文说明。'*4000+'\n长文末尾-K05：原件应完整保留。','queued':'未发布标记-K02','withdrawn':'撤回标记-K03','private':'私有标记-K04'}.get(scenario,'# 采购手册\n材料到货后由质量验收，随后商务归档。\n采购标记-K01 · MATERIAL-CHECK')
    name={'long':'long.md','queued':'queued.md','withdrawn':'withdrawn.md','private':'private.md'}.get(scenario,'published.md')
    document=seed(k,name,text,publish=scenario!='queued')
    if scenario=='withdrawn':ok(mutation(admin,'POST',base+'/documents/'+document['id']+'/actions',{'revision':document['revision'],'action':'withdraw'}))
    if scenario=='cross_project':base=base.replace(project['id'],add_project(admin,'FROZEN-OTHER')['id'])
    if scenario=='revoked':ok(grant(admin,project,person,['采购'],revision=1,active=False))
    client=admin if spec['actor']=='owner' else reader
    response=mutation(client,'POST',base+'/search',{'query':spec['query']})
    hits=response.json().get('results',[]);names=sorted(set(h['name'] for h in hits));hashes=[]
    if response.status_code==200:
        assert all(h['content'] in text for h in hits)
        if spec.get('original_hash'):
            for hit in hits:
                raw=client.get(hit['original_url']);raw.raise_for_status()
                hashes.append(hashlib.sha256(raw.content).hexdigest()==hashlib.sha256(text.encode()).hexdigest())
    record(record_property,spec,'retrieval',{'status':response.status_code,'names':names,'original_hash_matches':hashes})
    assert response.status_code==spec['status'] and names==spec['names']
    if spec.get('original_hash'):assert hashes and all(hashes)


def condition():
    nodes=[{'id':n,'kind':k,'label':n,'config':c} for n,k,c in [('start','start',{}),('gate','condition',{'source':'{{input}}','operator':'contains','value':'到货'}),('yes','template',{'template':'质量验收'}),('no','template',{'template':'等待到货'}),('out','output',{'template':'{{previous.output}}'})]]
    edges=[{'id':a+'-'+b,'source':a,'target':b,**({'sourceHandle':h} if h else {})} for a,b,h in [('start','gate',None),('gate','yes','true'),('gate','no','false'),('yes','out',None),('no','out',None)]]
    return {'name':'固定条件分支','nodes':nodes,'edges':edges}


@pytest.mark.parametrize('spec',SPECS['rules'],ids=lambda s:s['id'])
def test_frozen_rules(knowledge,spec,record_property):
    _,admin,_,_,reader,_,base=knowledge;scenario=spec['scenario']
    definition=condition() if scenario=='condition' else graph('{{input}}'*60) if scenario=='node_failure' else graph()
    if scenario=='invalid_graph':definition['edges'].append({'id':'cycle','source':'out','target':'start'})
    response=mutation(admin,'POST',base+'/applications',{'definition':definition})
    if scenario=='invalid_graph':
        record(record_property,spec,'rules',{'status':response.status_code});assert response.status_code==spec['status'];return
    application=ok(response);path=base+'/applications/'+application['id'];input=spec.get('input','材料')
    valid={'revision':1,'cases':[{'input':'材料','expectContains':'核对'}]}
    if scenario=='invalid_input':
        response=mutation(admin,'POST',path+'/run',{'input':input,'mode':'draft'})
        record(record_property,spec,'rules',{'status':response.status_code});assert response.status_code==spec['status'];return
    if scenario=='node_failure':
        r=ok(mutation(admin,'POST',path+'/evaluate',{'revision':1,'cases':[{'input':'长'*spec['input_length'],'expectContains':'不会出现'}]}))['cases'][0]
        nodes=[s['node_id'] for s in r['steps'] if s['status']=='failed']
        record(record_property,spec,'rules',{'actual_status':r['actual_status'],'failed_nodes':nodes})
        assert r['actual_status']==spec['expected_status'] and nodes==[spec['failed_node']];return
    if scenario=='evaluation_replay':
        r=ok(mutation(admin,'POST',path+'/evaluate',valid,key='frozen-eval-replay'));again=ok(mutation(admin,'POST',path+'/evaluate',valid,key='frozen-eval-replay'))
        record(record_property,spec,'rules',{'passed':r['passed'],'total':r['total'],'same_id':r['id']==again['id']})
        assert r==again and r['passed']==spec['passed'] and r['total']==spec['total'];return
    if scenario=='condition':
        cases=[{'input':input,'expectContains':spec['expected_output']}]
        ok(mutation(admin,'POST',path+'/publish',{'revision':1,'cases':cases}))
    else:ok(mutation(admin,'POST',path+'/publish',valid))
    response_status=None
    if scenario=='wrong_expectation':
        ok(mutation(admin,'PUT',path,{'revision':1,'definition':graph('新版：{{input}}')}))
        response=mutation(admin,'POST',path+'/publish',{'revision':2,'cases':[{'input':input,'expectContains':spec['expected']}]});response_status=response.status_code
    if scenario in {'draft_isolation','rollback'}:
        ok(mutation(admin,'PUT',path,{'revision':1,'definition':graph('新版：{{input}}')}))
        if scenario=='rollback':
            ok(mutation(admin,'POST',path+'/publish',{'revision':2,'cases':[{'input':input,'expectContains':'新版'}]}))
            ok(mutation(admin,'POST',path+'/rollback',{'revision':2,'target_revision':1}))
    result=ok(mutation(reader,'POST',path+'/run',{'input':input}));observed={'output':result['output'],'status':response_status}
    if scenario=='draft_isolation':observed['draft_output']=ok(mutation(admin,'POST',path+'/run',{'input':input,'mode':'draft'}))['output']
    record(record_property,spec,'rules',observed)
    assert result['output']==spec['expected_output']
    if 'status' in spec:assert response_status==spec['status']
    if 'draft_output' in spec:assert observed['draft_output']==spec['draft_output']
