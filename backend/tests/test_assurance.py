import io,json,zipfile,uuid,hashlib
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from sqlalchemy import select,func,text
from sqlalchemy.exc import DatabaseError
from test_cost import cost,env,board as costboard,checked,row,commit,ok,setup_close,close,publish,upload,job,get as getbatch,action as batchact
from test_pilot_foundation import grant,mutation,add_project
from app.handoff_models import Document
from app.assurance_models import ExceptionCase,ExceptionEvent,EvidenceExport,DataContract
from app.assurance_service import reconcile
from app.evidence_export import run_export,csvsafe
from app.data_bundle import backup,restore

def base(c):return '/api/projects/'+c['p']['id']+'/assurance'
def board(c,who='manager'):
 r=c['cs'][who].get(base(c)+'/board');return ok(r)
def overdue(c):
 aid=c['people']['manager']['id']
 with c['app'].state.store.transaction(write=True) as db:
  d=Document(id=uuid.uuid4().hex,project_id=c['p']['id'],kind='requirement',draft={'title':'合成交底','summary':'合成需求','source':'QA','attachment_ids':[],'brief_due_at':'2000-01-01T00:00:00+00:00'},created_by=aid,updated_by=aid);db.add(d);db.flush();return d.id

def case(c,who='manager'):return board(c,who)['exceptions'][0]
def act(c,e,name,who='manager',**kw):return mutation(c['cs'][who],'POST',base(c).removeprefix('/api')+'/exceptions/'+e['id']+'/actions',{'revision':e['revision'],'action':name,**kw})
def proof(c,e):
 client=c['cs']['manager'];return ok(client.post(base(c)+'/exceptions/'+e['id']+'/files',files={'file':('synthetic-approval.md',b'Synthetic existing approval; not real authority','text/plain')},headers={'X-Idempotency-Key':uuid.uuid4().hex,'X-CSRF-Token':client.get('/api/session').json()['csrf']}))['id']
def export(c,who='manager',sensitive=False,key=None):return ok(mutation(c['cs'][who],'POST',base(c).removeprefix('/api')+'/exports',{'confirmed':True,'include_sensitive':sensitive,'reason':'合成本机授权导出'},key))
def download(c,e,who='manager'):return c['cs'][who].get(base(c)+'/exports/'+e['id']+'/download')

def test_exception_dedup_read_remind_no_manual_close_and_fact_resolution(cost):
 oid=overdue(cost);e=case(cost);assert e['object_id']==oid and e['state']=='open'
 for _ in range(3):assert len(board(cost)['exceptions'])==1
 ok(act(cost,e,'read'));e=case(cost);ok(act(cost,e,'remind'));e=case(cost);assert e['state']=='open';assert act(cost,e,'remind').status_code==409;assert act(cost,e,'close').status_code==422
 with cost['app'].state.store.transaction(write=True) as db:d=db.get(Document,oid);d.has_draft=False
 assert case(cost)['state']=='resolved'
 with cost['app'].state.store.transaction(write=True) as db:d=db.get(Document,oid);d.has_draft=True
 assert case(cost)['state']=='open' and len(board(cost)['exceptions'])==1

def test_waiver_requires_evidence_expiry_and_preserves_underlying_fact(cost):
 overdue(cost);e=case(cost);until=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat();assert act(cost,e,'waive',reason='已有批准',until=until,approval_no='SYN').status_code==422
 fid=proof(cost,e);ok(act(cost,e,'waive',reason='合成既有批准只豁免提醒',until=until,approval_no='SYN',file_ids=[fid]));e=case(cost);assert e['state']=='waived'
 with cost['app'].state.store.transaction(write=True) as db:
  stored=db.get(ExceptionCase,e['id']);stored.waiver_until='2000-01-01T00:00:00+00:00';assert db.get(Document,e['object_id']).has_draft
 assert case(cost)['state']=='open' and any(x['action']=='waiver.expired' for x in case(cost)['events'])

def test_assign_valid_member_cas_and_regular_owner_visibility(cost):
 overdue(cost);e=case(cost);assert act(cost,e,'assign',owner_id='foreign',reason='x').status_code==422
 ok(act(cost,e,'assign',owner_id=cost['people']['reader']['id'],reason='合成指派'));assert act(cost,e,'read').status_code==409
 regular=case(cost,'reader');assert not regular['can_manage'];assert act(cost,regular,'waive',who='reader',reason='x').status_code==403
 assert len(board(cost,'reader')['exceptions'])==1

def test_finance_exception_never_exposed_to_pm_or_ordinary_roles(cost):
 bad=checked(cost,[row(unit='')]);assert getbatch(cost,bad)['state']=='invalid';assert not board(cost)['exceptions'] and not board(cost,'reader')['exceptions'];e=case(cost,'finance');assert e['financial'] and e['source_kind']=='cost_batch'
 assert act(cost,e,'read').status_code==404
 assert act(cost,e,'assign',who='finance',owner_id=cost['people']['manager']['id'],reason='x').status_code==422
 ok(batchact(cost,bad,'withdraw',reason='合成错误表退回'));assert case(cost,'finance')['state']=='resolved'

def test_fresh_draft_does_not_become_overdue_and_contracts_are_frozen(cost):
 with cost['app'].state.store.transaction(write=True) as db:
  db.add(Document(id=uuid.uuid4().hex,project_id=cost['p']['id'],kind='requirement',draft={'title':'新草稿'},created_by=cost['people']['manager']['id'],updated_by=cost['people']['manager']['id']))
 assert not board(cost)['exceptions'];contracts=board(cost)['contracts'];assert len(contracts)==4 and all(x['version']==1 and x['body']['required'] and x['body']['authority'] for x in contracts)
 with pytest.raises(DatabaseError):
  with cost['app'].state.store.transaction(write=True) as db:db.execute(text("UPDATE assurance_contracts SET version=2"))

def test_export_actual_package_hashes_no_auth_data_and_csv_injection(cost):
 overdue(cost);e=case(cost);proof(cost,e);task=export(cost);assert run_export(cost['app'].state.store);r=download(cost,task);assert r.status_code==200
 with zipfile.ZipFile(io.BytesIO(r.content)) as z:
  manifest=json.loads(z.read('manifest.json'));objects=json.loads(z.read('objects.json'));assert objects['exceptions'] and objects['contracts'];assert 'password_hash' not in z.read('objects.json').decode() and 'csrf' not in z.read('objects.json').decode() and 'path' not in str(objects['exceptions'][0]['files'][0])
  for f in manifest['files']:assert hashlib.sha256(z.read(f['path'])).hexdigest()==f['sha256']
 assert csvsafe('=SUM(A1)')=="'=SUM(A1)" and csvsafe(' -2')=="' -2"


def test_export_pm_only_published_finance_summary_and_finance_explicit(cost):
 b=checked(cost);ok(commit(cost,b));setup_close(cost);cl=close(cost);publish(cost,cl)
 pm=export(cost);run_export(cost['app'].state.store)
 with zipfile.ZipFile(io.BytesIO(download(cost,pm).content)) as z:
  data=json.loads(z.read('objects.json'));assert data['cost']['snapshots'] and 'line_ids' not in data['cost']['snapshots'][0]['body'] and 'batches' not in data['cost'];assert not any('/cost/' in n for n in z.namelist())
 fin=export(cost,'finance',True);run_export(cost['app'].state.store)
 with zipfile.ZipFile(io.BytesIO(download(cost,fin,'finance').content)) as z:assert json.loads(z.read('objects.json'))['cost']['batches']
 ok(grant(cost['admin'],cost['p'],cost['people']['reader'],['采购'],revision=1))
 assert mutation(cost['cs']['reader'],'POST',base(cost).removeprefix('/api')+'/exports',{'confirmed':True,'include_sensitive':True,'reason':'x'}).status_code==403


def test_export_revocation_creator_scope_and_cached_request_recheck(cost):
 task=export(cost,key='assurance-key');run_export(cost['app'].state.store);assert download(cost,task,'reader').status_code==404
 ok(grant(cost['admin'],cost['p'],cost['people']['manager'],['采购'],revision=1));assert download(cost,task).status_code==404
 assert cost['cs']['manager'].get('/api/requests/assurance-key').status_code==404


def test_export_failed_or_tampered_original_never_succeeds_and_expired_lease_restores(cost):
 overdue(cost);e=case(cost);proof(cost,e);task=export(cost)
 with cost['app'].state.store.transaction(write=True) as db:x=db.get(EvidenceExport,task['id']);x.state='running';x.claim_id='crashed';x.lease_until='2000-01-01T00:00:00+00:00'
 assert run_export(cost['app'].state.store);assert download(cost,task).status_code==200
 with cost['app'].state.store.transaction() as db:path=Path(db.get(EvidenceExport,task['id']).path)
 path.write_bytes(b'tampered');assert download(cost,task).status_code==409


def test_full_bundle_preserves_all_fact_fingerprints_and_revokes_old_sessions(cost,tmp_path):
 overdue(cost);e=case(cost);proof(cost,e);b=checked(cost);ok(commit(cost,b));setup_close(cost);cl=close(cost);publish(cost,cl)
 source=Path(cost['app'].state.store.engine.url.database).parent;archive=tmp_path/'backup.zip';manifest=backup(source,archive);after=restore(archive,tmp_path/'isolated')
 assert manifest['database']['fingerprints']==after['fingerprints'] and after['counts']['pilot_sessions']==0 and after['counts']['cost_snapshots']==1 and after['counts']['assurance_files']==1
 assert (archive.stat().st_mode&0o777)==0o600
 with pytest.raises(ValueError):restore(archive,tmp_path/'isolated')


def test_restore_rejects_tamper_traversal_and_missing_source(cost,tmp_path):
 archive=tmp_path/'source.zip';source=Path(cost['app'].state.store.engine.url.database).parent;backup(source,archive)
 bad=tmp_path/'bad.zip'
 with zipfile.ZipFile(archive) as z,zipfile.ZipFile(bad,'w') as out:
  for n in z.namelist():out.writestr(n,b'bad' if n=='pilot.db' else z.read(n))
 with pytest.raises(ValueError):restore(bad,tmp_path/'bad-target')
 assert not (tmp_path/'bad-target').exists()
 evil=tmp_path/'evil.zip'
 with zipfile.ZipFile(evil,'w') as z:z.writestr('../escape','x')
 with pytest.raises(ValueError):restore(evil,tmp_path/'evil-target')
 overdue(cost);proof(cost,case(cost));raw=next((source/'assurance-originals').iterdir());raw.unlink()
 with pytest.raises(ValueError):backup(source,tmp_path/'missing.zip')


def test_exception_cross_project_and_request_scope(cost):
 overdue(cost);e=case(cost);other=add_project(cost['admin'],'ASSURANCE-OTHER');r=cost['cs']['reader'].get('/api/projects/'+other['id']+'/assurance/board');assert r.status_code==404
 assert cost['cs']['reader'].get(base(cost)+'/files/'+uuid.uuid4().hex).status_code==404


def test_legacy_rehearsal_preserves_demo_unverified_author_original_and_missing_evidence(tmp_path):
 from app.legacy_rehearsal import rehearse
 original=tmp_path/'redacted.md';original.write_bytes(b'synthetic redacted original')
 source=tmp_path/'old.json';source.write_text(json.dumps({'schema_version':1,'data_mode':'synthetic','packages':[{'id':'reqpkg-demo-01','owner':'demo','version':2,'projectName':'合成旧项目','summary':'旧需求','attachments':['missing.pdf'],'history':[{'by':'商务-历史角色'}]},{'id':'redacted-02','version':3,'attachments':['redacted.md']}],'originals':{'redacted.md':{'relative_path':'redacted.md','sha256':hashlib.sha256(original.read_bytes()).hexdigest()}}}))
 report=rehearse(source,tmp_path/'migrated');assert report['source_packages']==report['proposals']==2 and report['demonstration_excluded']==1 and report['missing_originals']==report['originals_verified']==1 and report['business_activated']==0
 assert report['mappings'][0]['actor_id'] is None and report['mappings'][0]['legacy_authors']==['商务-历史角色'] and report['mappings'][1]['source_version_number_preserved']==3
 assert (tmp_path/'migrated/source.json').read_bytes()==source.read_bytes()
 with pytest.raises(ValueError):rehearse(source,tmp_path/'migrated')
 source.write_text(json.dumps({'schema_version':1,'data_mode':'unknown','packages':[]}))
 with pytest.raises(ValueError):rehearse(source,tmp_path/'unclassified')


def test_change_delivery_and_ack_are_distinct_versioned_deadline_exceptions(cost):
 from app.change_models import ChangeCase,ChangeVersion,ChangeAck
 from app.pilot_models import Outbox,Todo
 pid=cost['p']['id'];aid=cost['people']['manager']['id'];cid=uuid.uuid4().hex;vid=uuid.uuid4().hex
 with cost['app'].state.store.transaction(write=True) as db:
  db.add(ChangeCase(id=cid,project_id=pid,state='published',draft={'targets':[]},created_by=aid,current_version_id=vid));db.flush();db.add(ChangeVersion(id=vid,project_id=pid,case_id=cid,number=1,body={'recipients':[aid],'targets':[]},published_at='2000-01-01T00:00:00+00:00'))
 rows=board(cost)['exceptions'];assert len(rows)==2 and {x['rule_id'].split(':')[0] for x in rows}=={'change.delivery','change.ack'}
 with cost['app'].state.store.transaction(write=True) as db:
  event=Outbox(id=uuid.uuid4().hex,project_id=pid,recipient_id=aid,title='合成送达',target_id=cid,version_id=vid,state='done');db.add(event);db.flush();db.add(Todo(id=uuid.uuid4().hex,event_id=event.id,project_id=pid,recipient_id=aid,title='合成送达',target_id=cid,version_id=vid))
 assert len([x for x in board(cost)['exceptions'] if x['state']=='open'])==1
 with cost['app'].state.store.transaction(write=True) as db:db.add(ChangeAck(id=uuid.uuid4().hex,version_id=vid,actor_id=aid))
 assert all(x['state']=='resolved' for x in board(cost)['exceptions'])
