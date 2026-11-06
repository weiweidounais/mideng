"""Workspace navigation keeps live responsibility, source versions and role boundaries."""
from datetime import timedelta
import pytest
from sqlalchemy import select,func
from app.pilot_models import Todo,Outbox,utcnow
from app.pilot_service import uid
from app.handoff_models import Document,Version
from test_procurement import flow,ok,create,result,step,act,upload,archive_data,arrival,approved,get
from test_handoff import chain,post,scheme
from test_pilot_foundation import mutation,grant,add_project

def url(p,s):return '/api/projects/'+p['id']+'/workspace/'+s

def test_live_workbench_moves_responsibility_and_keeps_history(flow):
 (app,admin,p,cs,people),s=flow
 app.state.store.drain();b=cs['pm'].get('/api/workbench').json();assert any(t['link']['object_id']==s['id'] and t['pending'] for t in b['items'])
 o=ok(create(flow));b=cs['pm'].get('/api/workbench').json();assert all(t['link']['object_id']!=s['id'] for t in b['items'])
 app.state.store.drain();b=cs['purchase'].get('/api/workbench').json();assert any(t['link']['object_id']==o['id'] for t in b['items'])
 o=step(flow,o,'accept_purchase','purchase');o=step(flow,o,'submit_result','purchase',result={'supplier':'合成','lines':[{'line_no':1,'quantity':'0.3','eta':'2026-12-01'}]})
 app.state.store.drain();b=cs['pm'].get('/api/workbench').json();task=next(t for t in b['items'] if t['link']['object_id']==o['id']);assert task['link']['state']=='pm_review' and task['link']['version_id']==o['version_id']
 app.state.store.drain();b=cs['purchase'].get('/api/workbench').json();assert not any(t['link']['object_id']==o['id'] for t in b['items'])
 assert any(t['link']['object_id']==o['id'] and not t['pending'] for t in cs['purchase'].get('/api/workbench?mode=all').json()['items'])

def test_bounded_summary_detail_exact_comparison_and_source(flow):
 (_,_,p,cs,_),s=flow;o=result(flow);c=cs['pm']
 r=c.get(url(p,'procurement?page_size=1')).json();assert r['total']==1 and len(r['items'])==1 and 'lines' not in r['items'][0] and 'archive' not in r['items'][0]
 d=c.get(url(p,'purchase-orders/'+o['id']));assert d.status_code==200,d.text;d=d.json();assert d['source']['object_id']==s['id'] and d['source_number']==1 and d['source_current']
 line=d['comparison'][0];assert line['required_quantity']=='0.3' and line['ordered_quantity']=='0.3' and not line['quantity_changed'] and not line['late_eta']
 assert c.get(url(p,'bom-options')).json()['total']==0
 assert c.get(url(p,'procurement?page=2&page_size=1')).json()['items']==[]
 assert c.get(url(p,'procurement?page_size=51')).status_code==422

def test_quantity_and_late_date_flags_use_decimal(flow):
 (_,_,p,cs,_),_=flow;o=step(flow,ok(create(flow)),'accept_purchase','purchase');o=step(flow,o,'submit_result','purchase',result={'supplier':'合成','lines':[{'line_no':1,'quantity':'0.4','eta':'2026-12-02'}],'note':'额外损耗，日期差异待复核'})
 d=cs['pm'].get(url(p,'purchase-orders/'+o['id'])).json();assert d['comparison'][0]['quantity_changed'] and d['comparison'][0]['late_eta']
 assert act(flow,o,'approve_purchase','pm').status_code==422

def test_location_project_version_kind_and_revocation_guards(flow):
 (_,admin,p,cs,people),s=flow;o=ok(create(flow));c=cs['pm'];loc='locate?section=procurement&kind=procurement&object_id='+o['id']
 assert c.get(url(p,loc)).status_code==200
 assert c.get(url(p,loc+'&version_id=other')).status_code==404
 assert c.get(url(p,'locate?section=requirements&kind=procurement&object_id='+s['id'])).status_code==422
 p2=add_project(admin,'OTHER');assert c.get(url(p2,loc)).status_code==404
 assert cs['outsider'].get(url(p,loc)).status_code==404
 assert c.get(url(p,'locate?section=requirements&version_id='+s['versions'][0]['id'])).status_code==422
 membership=next(m for m in admin.get('/api/projects/'+p['id']+'/members').json() if m['account_id']==people['pm']['id'])
 assert grant(admin,p,people['pm'],['项目经理'],active=False,revision=membership['revision']).status_code==200
 assert c.get(url(p,loc)).status_code==404 and c.get('/api/workbench').json()['items']==[]

def test_document_index_draft_visibility_context_and_wrong_version(flow):
 (_,_,p,cs,_),s=flow;c=cs['pm'];idx=c.get(url(p,'documents')).json();assert idx['total']==1 and 'body' not in idx['items'][0]
 ctx=c.get(url(p,'document-context/'+s['id']+'?version_id='+s['versions'][0]['id']));assert ctx.status_code==200,ctx.text;assert len(ctx.json()['documents'])==2 and ctx.json()['contracts']==[]
 req=next(d for d in ctx.json()['documents'] if d['kind']=='requirement')
 assert c.get(url(p,'document-context/'+s['id']+'?version_id='+req['versions'][0]['id'])).status_code==404
 draft=ok(post(cs['market'],p,'/documents',{'kind':'requirement','body':{'title':'私有草稿','summary':'草稿','source':'合成'}}))
 assert c.get(url(p,'documents')).json()['total']==1
 assert c.get(url(p,'document-context/'+draft['id'])).status_code==404
 assert cs['biz'].get(url(p,'documents')).json()['total']==2

def test_workbench_dedup_pagination_and_read_only(flow):
 (app,_,p,cs,people),_=flow;o=ok(create(flow));c=cs['purchase']
 app.state.store.drain()
 with app.state.store.transaction() as db:
  t=db.scalar(select(Todo).where(Todo.recipient_id==people['purchase']['id'],Todo.target_id==o['id']))
  event=Outbox(id=uid(),project_id=t.project_id,recipient_id=t.recipient_id,title=t.title);db.add(event);db.flush()
  db.add(Todo(id=uid(),event_id=event.id,project_id=t.project_id,recipient_id=t.recipient_id,title=t.title,target_kind=t.target_kind,target_id=t.target_id,version_id=t.version_id))
  before=db.scalar(select(func.count()).select_from(Todo))
 r=c.get('/api/workbench?page_size=1').json();assert r['total']==1 and len(r['items'])==1
 assert c.get('/api/workbench?page=2&page_size=1').json()['items']==[]
 with app.state.store.transaction() as db:assert db.scalar(select(func.count()).select_from(Todo))==before

from test_cost import cost,checked,commit,setup_close,close,publish,board as cost_board
from test_pilot_foundation import env

def test_finance_source_snapshot_location_and_role_revoke(cost):
 c=cost;b=checked(c);ok(commit(c,b));setup_close(c);cl=close(c);publish(c,cl);snap=cost_board(c)['snapshots'][0];p=c['p']
 path='locate?section=cost&kind=cost_batch&object_id='+b['id']+'&version_id='+c['profile']
 assert c['cs']['finance'].get(url(p,path)).status_code==200
 assert c['cs']['manager'].get(url(p,path)).status_code==404
 public='locate?section=cost&kind=cost_snapshot&object_id='+snap['id']+'&version_id='+snap['id']
 assert c['cs']['manager'].get(url(p,public)).status_code==200
 assert c['cs']['reader'].get(url(p,public)).status_code==404
 m=next(m for m in c['admin'].get('/api/projects/'+p['id']+'/members').json() if m['account_id']==c['people']['finance']['id'])
 assert grant(c['admin'],p,c['people']['finance'],['采购'],revision=m['revision']).status_code==200
 assert c['cs']['finance'].get(url(p,path)).status_code==404
 assert all(t['link']['kind']!='cost_batch' for t in c['cs']['finance'].get('/api/workbench?mode=all').json()['items'])

def test_bom_action_visibility_tracks_current_design_recipient(flow):
 (_,admin,p,cs,people),_=flow
 from test_pilot_foundation import add_account,user_client
 app=flow[0][0];other=add_account(admin,'otherpm');assert grant(admin,p,other,['项目经理']).status_code==200
 with user_client(app,'otherpm') as c:
  assert c.get(url(p,'bom-options')).json()['items'][0]['can_request'] is False
  assert cs['pm'].get(url(p,'bom-options')).json()['items'][0]['can_request'] is True
  m=next(m for m in admin.get('/api/projects/'+p['id']+'/members').json() if m['account_id']==people['pm']['id'])
  assert grant(admin,p,people['pm'],['采购'],revision=m['revision']).status_code==200
  assert c.get(url(p,'bom-options')).json()['items'][0]['can_request'] is True
