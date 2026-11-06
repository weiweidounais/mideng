"""Role filtering and real database pagination, without weakening the financial ledger gates."""
from sqlalchemy import select
from app.cost_models import CostBatch
from test_cost import cost,checked,commit,setup_close,close,publish,row,board,upload
from test_pilot_foundation import env,grant,add_project

def endpoint(c,s='workspace'):return '/api/projects/'+c['p']['id']+'/cost/'+s

def test_summary_counts_and_all_normalized_pages(cost):
 c=cost;b=checked(c,[row('R'+str(i),value='0.01') for i in range(147)]);client=c['cs']['finance']
 w=client.get(endpoint(c));assert w.status_code==200,w.text;w=w.json();assert w['batch_total']==1
 s=w['batches'][0];assert s['rows_count']==s['normalized_count']==147 and s['rows']==s['normalized']==s['errors']==[]
 rows=[]
 for page in range(1,9):
  r=client.get(endpoint(c,'batches/'+b['id']+'/review-rows'),params={'kind':'normalized','revision':s['revision'],'page':page});assert r.status_code==200,r.text;v=r.json();assert v['total']==147;rows+=v['items']
 assert len(rows)==147 and len({r['source_key'] for r in rows})==147 and sum(len(r['amount'])>0 for r in rows)==147
 assert client.get(endpoint(c,'batches/'+b['id']+'/review-rows'),params={'kind':'normalized','revision':s['revision'],'page':9}).json()['items']==[]
 # The old endpoint stays compatible and complete.
 assert len(client.get(endpoint(c,'batches/'+b['id'])).json()['normalized'])==147

def test_errors_page_raw_values_and_revision_guard(cost):
 c=cost;b=checked(c,[row('BAD'+str(i),unit='') for i in range(45)]);client=c['cs']['finance'];s=client.get(endpoint(c)).json()['batches'][0]
 r=client.get(endpoint(c,'batches/'+b['id']+'/review-rows'),params={'kind':'errors','revision':s['revision'],'page':2});assert r.status_code==200,r.text;r=r.json();assert r['total']==45 and r['validation_error_total']==45 and len(r['items'])==20 and r['items'][0]['row']==22
 conflict=client.get(endpoint(c,'batches/'+b['id']+'/review-rows'),params={'kind':'errors','revision':s['revision']-1});assert conflict.status_code==409 and conflict.json()['error']['current_revision']==s['revision']
 assert client.get(endpoint(c,'batches/'+b['id']+'/review-rows'),params={'kind':'errors','revision':s['revision'],'page_size':51}).status_code==422
 assert commit(c,b).status_code==409

def test_finance_role_revoke_and_pm_summary_do_not_expose_private_data(cost):
 c=cost;b=checked(c);assert commit(c,b).status_code==200;setup_close(c);cl=close(c);publish(c,cl)
 m=c['cs']['manager'].get(endpoint(c)).json();assert m['batches']==m['files']==m['profiles']==m['closes']==[] and m['batch_total']==m['close_total']==0 and m['snapshots'] and 'line_ids' not in m['snapshots'][0]['body']
 assert c['cs']['reader'].get(endpoint(c)).json()['snapshots']==[]
 params={'kind':'rows','revision':1}
 assert c['cs']['manager'].get(endpoint(c,'batches/'+b['id']+'/review-rows'),params=params).status_code==403
 member=next(m for m in c['admin'].get('/api/projects/'+c['p']['id']+'/members').json() if m['account_id']==c['people']['finance']['id'])
 assert grant(c['admin'],c['p'],c['people']['finance'],['采购'],revision=member['revision']).status_code==200
 assert c['cs']['finance'].get(endpoint(c)).json()['batches']==[]
 assert c['cs']['finance'].get(endpoint(c,'replacement-options'),params={'profile_id':c['profile']}).status_code==403

def test_workspace_page_counts_located_batch_and_replacement_options(cost):
 c=cost;client=c['cs']['finance'];ids=[]
 for i in range(3):
  b=checked(c,[row('R'+str(i))]);assert commit(c,b).status_code==200;ids.append(b['id'])
 r=client.get(endpoint(c),params={'batch_page':2,'page_size':2}).json();assert r['batch_total']==3 and len(r['batches'])==1
 located=client.get(endpoint(c),params={'kind':'cost_batch','object_id':ids[0]}).json();assert [b['id'] for b in located['batches']]==[ids[0]]
 opts=client.get(endpoint(c,'replacement-options'),params={'profile_id':c['profile'],'page':2,'page_size':2});assert opts.status_code==200,opts.text;assert opts.json()['total']==3 and len(opts.json()['items'])==1
 p=add_project(c['admin'],'OTHER');assert client.get('/api/projects/'+p['id']+'/cost/workspace').status_code==404

def test_error_storage_limit_is_explicit_and_never_hides_validation_total(cost):
 c=cost;b=checked(c,[row('LIMIT'+str(i),unit='',subject_code='UNKNOWN',wbs_code='UNKNOWN') for i in range(400)])
 w=c['cs']['finance'].get(endpoint(c)).json()['batches'][0]
 assert w['state']=='invalid' and w['errors_count']==1000 and w['differences']['error_count']==1200
 r=c['cs']['finance'].get(endpoint(c,'batches/'+b['id']+'/review-rows'),params={'kind':'errors','revision':w['revision'],'page':50}).json()
 assert r['total']==1000 and r['validation_error_total']==1200 and len(r['items'])==20
 assert commit(c,b).status_code==409
