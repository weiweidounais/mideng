import csv,io,json,uuid,copy
from datetime import datetime,timezone
from pathlib import Path
import pytest
from sqlalchemy import select,func,text
from sqlalchemy.exc import DatabaseError
from app.cost_models import CostBatch,CostLine,CostClose,CostSource,CostSnapshot
from app.cost_service import run_job,ledger,due_at
from app.cost_import import FIELDS
from test_pilot_foundation import env,add_project,add_account,grant,user_client,mutation
NOW=datetime.now(timezone.utc).isoformat()
PERIOD='2026-10'
@pytest.fixture
def cost(env):
 app,admin=env;p=add_project(admin);cs={};people={}
 for who,roles in [('finance',['财务']),('manager',['项目经理']),('reader',['采购','商务'])]:
  a=add_account(admin,who);people[who]=a;assert grant(admin,p,a,roles).status_code==200;cs[who]=user_client(app,who)
 c={'app':app,'admin':admin,'p':p,'cs':cs,'people':people}
 profile=ok(post(c,'/profiles',{'source_system':'SYN-ERP','name':'合成财务映射','subjects':{'6601':'成本'},'wbs':{'W1':'项目WBS1'},'basis':'合成财务确认源ID唯一且科目/WBS归集正确','estimate_policy':'separate'}));c['profile']=profile['id']
 yield c
 for client in cs.values():client.close()
def ok(r):assert r.status_code==200,r.text;return r.json()
def base(c):return '/projects/'+c['p']['id']+'/cost'
def post(c,path,body,who='finance',key=None):return mutation(c['cs'][who],'POST',base(c)+path,body,key)
def board(c,who='finance'):
 r=c['cs'][who].get('/api'+base(c)+'/board');assert r.status_code==200,r.text;return r.json()
def row(id='R1',value='100.10',kind='实际',**kw):return {'source_id':id,'line_version':'1','project_code':'P1','entry_date':'2026-10-15','subject_code':'6601','wbs_code':'W1','kind':kind,'business_id':'BUS-'+id,'amount':value,'quantity':'1','unit':'笔','currency':'CNY','tax_basis':'含税',**kw}
def csvbytes(rows,ending='\r\n'):
 out=io.StringIO();w=csv.writer(out,lineterminator=ending);w.writerow(FIELDS.values())
 for r in rows:w.writerow([r.get(k,'') for k in FIELDS])
 return ('\ufeff'+out.getvalue()).encode('utf-8')
def upload(c,rows=None,raw=None,name='cost.csv',**meta):
 data={'profile_id':c['profile'],'period':PERIOD,'currency':'CNY','tax_basis':'含税','mode':'increment','replace_ids':[],'reason':'合成财务核对导入','exported_at':NOW,'data_cutoff':'2026-10-31T15:59:59+00:00',**meta};client=c['cs']['finance'];r=client.post('/api'+base(c)+'/batches',data={'meta':json.dumps(data)},files={'file':(name,csvbytes(rows or [row()]) if raw is None else raw,'text/csv')},headers={'X-CSRF-Token':client.get('/api/session').json()['csrf'],'X-Idempotency-Key':uuid.uuid4().hex});return ok(r)
def job(c):assert run_job(c['app'].state.store)
def get(c,b):return ok(c['cs']['finance'].get('/api'+base(c)+'/batches/'+b['id']))
def action(c,b,name,**kw):
 latest=get(c,b);return post(c,'/batches/'+b['id']+'/actions',{'revision':latest['revision'],'action':name,**kw})
def checked(c,rows=None,**kw):
 b=upload(c,rows,**kw);job(c);assert get(c,b)['state']=='mapping';ok(action(c,b,'mapping',mapping=FIELDS));job(c);return b
def commit(c,b):return action(c,b,'commit',confirmed=True,reason='财务已核对预检/差异、来源范围和确定金额')
def evidence(c):
 client=c['cs']['finance'];r=client.post('/api'+base(c)+'/evidence',files={'file':('approval.md',b'Synthetic existing budget or revenue approval; QA only','text/plain')},headers={'X-CSRF-Token':client.get('/api/session').json()['csrf'],'X-Idempotency-Key':uuid.uuid4().hex});return ok(r)['id']
def setup_close(c,budget='100.00'):
 fid=evidence(c);ok(post(c,'/budgets',{'currency':'CNY','tax_basis':'含税','kind':'baseline','amount':budget,'approval_no':'SYN-BUDGET','basis':'合成已确认业务预算','file_ids':[fid]}));cal=ok(post(c,'/calendars',{'name':'合成公司日历','start':'2026-11-01','end':'2026-11-15','workdays':['2026-11-03','2026-11-04','2026-11-05'],'basis':'明确11月1/2非工作，3/4/5为公司工作日'}));c['calendar']=cal['id'];return fid
def close(c,control='100.10',**kw):return ok(post(c,'/closes',{'period':PERIOD,'currency':'CNY','tax_basis':'含税','calendar_id':c.get('calendar'),'control_total':control,'control_basis':'会计实际加待分摊的本期间源系统控制总额','reason':'合成月结核对','allow_partial':False,**kw}))
def current_close(c,cl):return next(x for x in board(c)['closes'] if x['id']==cl['id'])
def ca(c,cl,name,**kw):return post(c,'/closes/'+cl['id']+'/actions',{'revision':current_close(c,cl)['revision'],'action':name,**kw})
def publish(c,cl):ok(ca(c,cl,'submit_review'));return ok(ca(c,cl,'publish',confirmed=True,reason='财务明确核对范围、口径和原件后发布'))

@pytest.mark.parametrize('bad',[{'unit':''},{'subject_code':'UNKNOWN'},{'wbs_code':'UNKNOWN'},{'source_id':''},{'amount':'=1+2'},{'amount':'0.001'},{'currency':'USD'},{'tax_basis':'不含税'},{'entry_date':'2026-09-15'}])
def test_invalid_row_blocks_entire_batch_and_keeps_field_errors(cost,bad):
 b=checked(cost,[row(),row('R2',**bad)]);data=get(cost,b);assert data['state']=='invalid' and data['errors'] and data['errors'][0]['row']==3;assert commit(cost,b).status_code==409
 with cost['app'].state.store.transaction() as db:assert not ledger(db,cost['p']['id'])

def test_precise_commit_reimport_and_explicit_cumulative_replacement(cost):
 b=checked(cost,[row(value='0.10'),row('R2','0.20')]);ok(commit(cost,b));duplicate=checked(cost,[row(value='0.10'),row('R2','0.20')],raw=csvbytes([row(value='0.10'),row('R2','0.20')],ending='\n'));assert get(cost,duplicate)['differences']['duplicate_rows']==2;ok(commit(cost,duplicate))
 setup_close(cost,'0');cl=close(cost,'0.30');data=current_close(cost,cl)['body'];assert data['actual_accounting']=='0.30' and data['variance_rate'] is None and data['gross_margin'] is None
 # A new row version cannot be added over the old active version.
 inc=checked(cost,[row(value='0.15',line_version='2'),row('R2','0.25',line_version='2')]);assert get(cost,inc)['state']=='invalid';ok(action(cost,inc,'withdraw',reason='累计修正改为显式替换'))
 replacement=checked(cost,[row(value='0.15',line_version='2'),row('R2','0.25',line_version='2')],mode='replace',replace_ids=[b['id'],duplicate['id']]);ok(commit(cost,replacement));assert get(cost,b)['state']=='replaced';assert current_close(cost,cl)['body']['actual_accounting']=='0.30';assert ca(cost,cl,'submit_review').status_code==409
 refreshed=ok(ca(cost,cl,'refresh',replacement={'period':PERIOD,'currency':'CNY','tax_basis':'含税','calendar_id':cost['calendar'],'control_total':'0.40','control_basis':'新来源控制','reason':'重新核对'}));assert current_close(cost,cl)['body']['actual_accounting']=='0.40'

def test_estimate_actual_payment_invoice_not_double_counted_and_reversal_chain(cost):
 est=checked(cost,[row('EST','20.00','暂估',business_id='B')]);ok(commit(cost,est))
 wrong=checked(cost,[row('ACT','22.00',business_id='B')]);assert get(cost,wrong)['state']=='invalid';ok(action(cost,wrong,'withdraw',reason='补充明确暂估冲正'))
 rev=row('REV','-20.00','冲正',business_id='B',quantity='-1',related_source='SYN-ERP',related_period=PERIOD,related_id='EST',related_version='1')
 actual=row('ACT','22.00',business_id='B',related_source='SYN-ERP',related_period=PERIOD,related_id='EST',related_version='1');b=checked(cost,[rev,actual,row('PAY','10.00','付款',business_id='B'),row('INV','22.00','发票',business_id='B'),row('ORDER','30.00','承诺',business_id='B')]);assert get(cost,b)['state']=='ready';ok(commit(cost,b));setup_close(cost);cl=close(cost,'22.00');v=current_close(cost,cl)['body'];assert v['actual_accounting']=='22.00' and v['estimate']=='0.00' and v['payment']=='10.00' and v['commitment']=='30.00' and v['invoice']=='22.00'
 assert action(cost,est,'withdraw',reason='破坏冲正链').status_code==409

def test_calendar_missing_and_known_control_mismatch_cannot_publish(cost):
 b=checked(cost);ok(commit(cost,b));cl=close(cost);assert '月结时限未配置或公司日历覆盖不足' in current_close(cost,cl)['body']['gaps'];assert ca(cost,cl,'submit_review').status_code==409
 setup_close(cost);wrong=close(cost,'999.00');assert ca(cost,wrong,'submit_review').status_code==409
 right=close(cost);assert current_close(cost,right)['body']['deadline']=='2026-11-05T15:59:59+00:00';publish(cost,right)

def test_snapshot_correction_immutable_old_publication_and_private_details(cost):
 b=checked(cost);ok(commit(cost,b));setup_close(cost);cl=close(cost);publish(cost,cl);snap=board(cost)['snapshots'][0]
 assert board(cost,'manager')['snapshots'][0]['body']['actual_accounting']=='100.10' and not board(cost,'manager')['batches'];assert 'line_ids' not in board(cost,'manager')['snapshots'][0]['body'];assert not board(cost,'reader')['snapshots']
 assert cost['cs']['manager'].get('/api'+base(cost)+'/batches/'+b['id']).status_code==403
 assert cost['cs']['reader'].get('/api'+base(cost)+'/files/'+get(cost,b)['source_id']).status_code==403
 extra=checked(cost,[row('R2','0.20')]);ok(commit(cost,extra));cor=close(cost,'100.30',correction_of=snap['id'],reason='迟到源表更正');publish(cost,cor);snapshots=board(cost)['snapshots'];assert len(snapshots)==2 and snapshots[0]['previous_id']==snap['id'] and snapshots[1]['body']['actual_accounting']=='100.10';assert current_close(cost,cl)['state']=='corrected'
 with pytest.raises(DatabaseError):
  with cost['app'].state.store.transaction(write=True) as db:db.execute(text('UPDATE cost_snapshots SET number=9'))

def test_real_xlsx_formula_and_duplicate_keys_rejected(cost):
 import openpyxl
 book=openpyxl.Workbook();sheet=book.active;sheet.append(list(FIELDS.values()));r=row(amount='=1+2');sheet.append([r.get(k,'') for k in FIELDS]);data=io.BytesIO();book.save(data);b=checked(cost,raw=data.getvalue(),name='formula.xlsx');assert get(cost,b)['state']=='invalid' and any('公式' in e['reason'] for e in get(cost,b)['errors'])
 dup=checked(cost,[row(),row()]);assert get(cost,dup)['state']=='invalid'

def test_expired_background_lease_resumes_after_restart_without_duplicate_write(cost):
 b=upload(cost)
 with cost['app'].state.store.transaction(write=True) as db:r=db.get(CostBatch,b['id']);r.state='running_parse';r.lease_until='2000-01-01T00:00:00+00:00';r.claim_id='stopped-process';r.attempts=1
 job(cost);assert get(cost,b)['state']=='mapping';ok(action(cost,b,'mapping',mapping=FIELDS));job(cost);ok(commit(cost,b));assert get(cost,b)['state']=='committed'

def test_precheck_generation_cas_and_commit_rollback(cost,monkeypatch):
 a=checked(cost,[row('A','0.10')]);b=checked(cost,[row('B','0.20')]);ok(commit(cost,a));assert commit(cost,b).status_code==409;ok(action(cost,b,'recheck'));job(cost)
 from app import cost_service
 def fault(*args,**kwargs):raise RuntimeError('commit failure')
 monkeypatch.setattr(cost_service,'event',fault)
 with pytest.raises(RuntimeError):commit(cost,b)
 assert get(cost,b)['state']=='ready'
 with cost['app'].state.store.transaction() as db:assert db.scalar(select(func.count()).select_from(CostLine))==1

def test_unallocated_unknown_scope_and_income_not_assumed(cost):
 b=checked(cost,[row('PENDING','100.00','待分摊')]);ok(commit(cost,b));setup_close(cost);cl=close(cost,'100.00');assert ca(cost,cl,'submit_review').status_code==409
 partial=close(cost,'100.00',allow_partial=True,partial_reason='已知待分摊，部分归集发布');body=current_close(cost,partial)['body'];assert body['unallocated']=='100.00' and body['completeness']=='0' and body['gross_margin'] is None;publish(cost,partial)

def test_zero_control_and_confirmed_income_require_evidence(cost):
 b=checked(cost,[row(value='0.00')]);ok(commit(cost,b));fid=setup_close(cost,'0');cl=close(cost,'0.00',revenue='10.00');assert ca(cost,cl,'submit_review').status_code==409
 right=close(cost,'0.00',revenue='10.00',revenue_comparable=True,revenue_basis='同口径合成确认收入',revenue_file_ids=[fid]);publish(cost,right);assert board(cost)['snapshots'][0]['body']['gross_margin']=='10.00' and board(cost)['snapshots'][0]['body']['variance_rate'] is None

def test_cross_project_source_and_revoked_cached_response_denied(cost):
 other=add_project(cost['admin'],'OTHER-COST');body={'source_system':'X','name':'X','subjects':{'A':'B'},'wbs':{'A':'B'},'basis':'X'};assert mutation(cost['cs']['finance'],'POST','/projects/'+other['id']+'/cost/profiles',body).status_code==404
 p=post(cost,'/profiles',body,key='cost-revoke');ok(p);assert grant(cost['admin'],cost['p'],cost['people']['finance'],['财务'],revision=1,active=False).status_code==200;assert cost['cs']['finance'].get('/api/requests/cost-revoke').status_code==404

def test_composite_keys_need_finance_confirmation_and_ambiguous_rows_fail(cost):
 body={'source_system':'NO-ID','name':'组合键','subjects':{'6601':'成本'},'wbs':{'W1':'项目WBS1'},'basis':'财务确认组合键规则','key_mode':'composite','key_fields':['document_no']};assert post(cost,'/profiles',body).status_code==422
 cost['profile']=ok(post(cost,'/profiles',body|{'key_fields':['document_no','document_line','entry_date']}))['id'];a=row(source_id='',document_no='DOC-1',document_line='1');b=checked(cost,[a]);assert get(cost,b)['state']=='ready';duplicate=checked(cost,[a,a],reason='组合键歧义验证');assert get(cost,duplicate)['state']=='invalid'

def test_cross_period_reversal_and_over_reversal_validation(cost):
 first=checked(cost);ok(commit(cost,first));rev=row('NOV-REV','-100.10','冲正',business_id='BUS-R1',quantity='-1',entry_date='2026-11-01',related_source='SYN-ERP',related_period=PERIOD,related_id='R1',related_version='1');nov=checked(cost,[rev],period='2026-11',data_cutoff=NOW);assert get(cost,nov)['state']=='ready';ok(commit(cost,nov))
 from app.cost_service import calculate
 with cost['app'].state.store.transaction() as db:
  body=calculate(db,cost['p']['id'],{'period':'2026-11','currency':'CNY','tax_basis':'含税','calendar_id':None,'control_total':'-100.10','control_basis':'跨期冲正范围'})
  assert body['actual_accounting']=='-100.10'
 over=checked(cost,[row('EXTRA-REV','-0.01','冲正',business_id='BUS-R1',quantity='-1',related_source='SYN-ERP',related_period=PERIOD,related_id='R1',related_version='1')]);assert get(cost,over)['state']=='invalid'

def test_currency_groups_are_separate_and_pending_estimate_policy_explicit(cost):
 cny=checked(cost);ok(commit(cost,cny));usd=checked(cost,[row('USD','999.00',currency='USD')],currency='USD');ok(commit(cost,usd));setup_close(cost);cl=close(cost);assert current_close(cost,cl)['body']['actual_accounting']=='100.10'
 include=ok(post(cost,'/profiles',{'source_system':'EST-ERP','name':'明确纳入净暂估','subjects':{'6601':'成本'},'wbs':{'W1':'项目WBS1'},'estimate_policy':'include','basis':'合成财务明确同口径净暂估纳入'}));cost['profile']=include['id'];est=checked(cost,[row('ESTONLY','10.00','暂估')]);ok(commit(cost,est));partial=close(cost);assert current_close(cost,partial)['body']['actual_reported']=='110.10' and current_close(cost,partial)['body']['estimate_included']=='10.00'

def test_row_limit_and_template_contract(cost):
 client=cost['cs']['finance'];r=client.get('/api'+base(cost)+'/template.xlsx');assert r.status_code==200
 import openpyxl
 book=openpyxl.load_workbook(io.BytesIO(r.content),read_only=True);assert [c.value for c in next(book.active.iter_rows())]==list(FIELDS.values());book.close()
 b=upload(cost,[row(str(i)) for i in range(5001)]);job(cost);assert get(cost,b)['state']=='invalid' and '5000' in get(cost,b)['errors'][0]['reason']

def test_two_finance_commits_from_same_precheck_have_one_winner(cost):
 from concurrent.futures import ThreadPoolExecutor
 a=checked(cost,[row('A','1.00')]);b=checked(cost,[row('B','2.00')])
 with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(lambda batch:commit(cost,batch).status_code,[a,b]))
 assert sorted(statuses)==[200,409]
 with cost['app'].state.store.transaction() as db:assert len(ledger(db,cost['p']['id']))==1

def test_stale_original_and_unknown_control_do_not_become_zero(cost):
 b=checked(cost);ok(commit(cost,b));setup_close(cost);unknown=close(cost,control=None,allow_partial=True,partial_reason='源系统未提供可信分母，只发布已核对部分');assert current_close(cost,unknown)['body']['completeness'] is None
 with cost['app'].state.store.transaction() as db:Path(db.get(CostSource,get(cost,b)['source_id']).path).write_bytes(b'changed')
 assert ca(cost,unknown,'submit_review').status_code==409
 for name in ['files','profiles','batches','closes','budgets']:assert not board(cost,'reader')[name]


def test_import_source_write_failure_cleans_file_and_rolls_back(cost,monkeypatch):
 from app import cost_service
 def fault(*args,**kwargs):raise RuntimeError('upload transaction fault')
 monkeypatch.setattr(cost_service,'event',fault)
 with pytest.raises(RuntimeError):upload(cost)
 with cost['app'].state.store.transaction() as db:assert db.scalar(select(func.count()).select_from(CostSource))==0
 folder=Path(cost['app'].state.store.engine.url.database).parent/'cost-originals';assert not list(folder.iterdir())


def test_upload_after_review_blocks_stale_publication_until_rechecked(cost):
 b=checked(cost);ok(commit(cost,b));setup_close(cost);cl=close(cost);ok(ca(cost,cl,'submit_review'))
 pending=upload(cost,[row('LATE','0.20')])
 # Upload has not committed a line or changed the ledger generation yet.
 r=ca(cost,cl,'publish',confirmed=True,reason='不能忽略草稿后的未处理批次')
 assert r.status_code==409 and r.json()['error']['code']=='CLOSE_STALE'
 assert not board(cost)['snapshots']
 ok(action(cost,pending,'withdraw',reason='财务确认不属于本次范围，保留原件'))
 ok(ca(cost,cl,'refresh'));publish(cost,cl)
 assert board(cost)['snapshots'][0]['body']['actual_accounting']=='100.10'
