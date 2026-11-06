"""Prepare isolated synthetic QA fixtures and verify additive form contracts over real HTTP."""
from pathlib import Path
from datetime import datetime,timezone
import csv,io,json,uuid,httpx,sys
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'backend'));P=R/'backend/.runtime/qa/browser-credentials.json';creds=json.loads(P.read_text());people=creds['procurement_v2']['people']|{'finance':creds['cost25']['people']['finance']};checks=[]
def login(u):
 c=httpx.Client(base_url='http://127.0.0.1:18411',trust_env=False,timeout=20);r=c.post('/api/auth/login',json={k:u[k] for k in ['username','password']});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
admin=login(creds);clients={k:login(v) for k,v in people.items()}
def post(c,path,body,method='POST'):
 r=c.request(method,'/api'+path,json=body,headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();return r.json()
if 'forms32' not in creds:
 suffix=uuid.uuid4().hex[:6];p=post(admin,'/projects',{'code':'QA32-'+suffix,'name':'复杂表单与成本核对（合成）'});pid=p['id'];base='/projects/'+pid
 for k,roles in [('market',['市场']),('biz',['商务']),('design',['设计']),('purchase',['采购']),('pm',['项目经理']),('quality',['质量']),('finance',['财务'])]:post(admin,base+'/members',{'account_id':people[k]['id'],'roles':roles,'revision':0},'PUT')
 profile=post(clients['finance'],base+'/cost/profiles',{'name':'QA32合成映射','source_system':'QA32-'+suffix,'subjects':{'6601':'生产成本'},'wbs':{'W1':'项目WBS1'},'basis':'仅用于本机合成验证','estimate_policy':'separate'})
 c=clients['finance'];f=c.post('/api'+base+'/cost/evidence',files={'file':('qa32-approval.md',b'Synthetic existing budget approval only','text/plain')},headers={'X-Idempotency-Key':uuid.uuid4().hex});f.raise_for_status();fid=f.json()['id']
 post(c,base+'/cost/budgets',{'currency':'CNY','tax_basis':'含税','kind':'baseline','amount':'1.00','approval_no':'SYN-QA32','basis':'合成预算基线','file_ids':[fid]})
 calendar=post(c,base+'/cost/calendars',{'name':'QA32合成公司日历','start':'2026-11-01','end':'2026-11-15','workdays':['2026-11-03','2026-11-04','2026-11-05'],'basis':'合成日历，明确公司工作日'})
 h=base+'/handoff';d=post(clients['market'],h+'/documents',{'kind':'requirement','body':{'title':'25行BOM表单验证需求','summary':'合成材料批量核对','source':'合成QA32'}});d=post(clients['biz'],h+'/documents/'+d['id']+'/publish',{'revision':d['revision'],'recipient_ids':[people['design']['id']],'diff_summary':'首次正式需求'})
 s=post(clients['design'],h+'/documents',{'kind':'scheme','parent_id':d['id'],'source_version_id':d['versions'][0]['id'],'body':{'title':'QA32 25行BOM草稿','notes':'保持草稿输入并分段核对','bom':[{'material':'合成管材'+str(i+1),'spec':'DN100','quantity':'1','unit':'米','need_by':'2026-12-01'} for i in range(25)]}})
 from app.cost_import import FIELDS
 def write_csv(name,bad):
  stream=io.StringIO();w=csv.writer(stream);w.writerow(FIELDS.values())
  for i in range(45 if bad else 47):
   row={'source_id':('BAD' if bad else 'GOOD')+str(i),'line_version':'1','project_code':p['code'],'entry_date':'2026-10-15','subject_code':'6601','wbs_code':'W1','kind':'实际','business_id':'QA32-'+str(i),'amount':'0.01','quantity':'1','unit':'' if bad else '笔','currency':'CNY','tax_basis':'含税'};w.writerow([row.get(k,'') for k in FIELDS])
  path=R/'backend/.runtime/qa'/name;path.write_text('\ufeff'+stream.getvalue());path.chmod(0o600);return str(path)
 creds['forms32']={'project_id':pid,'project_code':p['code'],'people':people,'profile_id':profile['id'],'calendar_id':calendar['id'],'evidence_id':fid,'requirement_id':d['id'],'scheme_id':s['id'],'bad_file':write_csv('qa32-bad.csv',True),'good_file':write_csv('qa32-good.csv',False)};P.write_text(json.dumps(creds));P.chmod(0o600)
data=creds['forms32'];pid=data['project_id'];base='/api/projects/'+pid+'/cost';c=clients['finance']
def check(name,value):assert value,name;checks.append({'name':name,'result':'通过'})
r=c.get(base+'/workspace');check('真实财务工作区可读且批次摘要有界',r.status_code==200 and r.json()['can_finance'])
r=clients['pm'].get(base+'/workspace');check('项目经理只读发布汇总，不读取财务源与草稿',r.status_code==200 and not r.json()['can_finance'] and r.json()['files']==r.json()['batches']==r.json()['closes']==[])
r=c.get(base+'/replacement-options',params={'profile_id':data['profile_id']});check('真实替换候选分页契约',r.status_code==200 and 'total' in r.json())
if data.get('good_batch'):
 from decimal import Decimal
 w=c.get(base+'/workspace').json();committed=[b for b in w['batches'] if b['state']=='committed'];check('响应丢失及并发核对后仅一批明确入账',len(committed)==1 and committed[0]['id']==data['good_batch'])
 b=next(b for b in w['batches'] if b['id']==data['good_batch']);lines=[]
 for page in [1,2,3]:
  r=c.get(base+'/batches/'+b['id']+'/review-rows',params={'kind':'normalized','revision':b['revision'],'page':page});r.raise_for_status();lines+=r.json()['items']
 check('47归集行分页完整且金额精确0.47',len(lines)==47 and len({r['source_key'] for r in lines})==47 and sum((Decimal(r['amount']) for r in lines),Decimal(0))==Decimal('0.47'))
 check('错误源表45项保留且未入账',any(b['id']==data['bad_batch'] and b['errors_count']==45 and b['state']=='withdrawn' for b in w['batches']))
 check('月结只发布一份0.47确认快照',len(w['snapshots'])==1 and w['snapshots'][0]['body']['actual_accounting']=='0.47')
 pm=clients['pm'].get(base+'/workspace').json();check('PM只读发布汇总，仍无财务源行和草稿',len(pm['snapshots'])==1 and pm['snapshots'][0]['body']['actual_accounting']=='0.47' and pm['batches']==pm['files']==pm['closes']==[])
 d=clients['design'].get('/api/projects/'+pid+'/handoff/documents/'+data['scheme_id']).json();check('25行BOM跨页保存与父正式来源保留',len(d['draft']['bom'])==25 and d['draft']['bom'][24]['material']=='修正后合成管材25' and bool(d['source_version_id']))
e=R/'docs/evidence/阶段3-2';e.mkdir(parents=True,exist_ok=True);(e/'真实接口检查.json').write_text(json.dumps({'environment':'QA18411 synthetic','checks':checks},ensure_ascii=False,indent=2)+'\n')
for c in [admin,*clients.values()]:c.close()
print({'checks':len(checks),'fixture_ready':True})
