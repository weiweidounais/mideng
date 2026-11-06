"""Real HTTP QA on isolated 18411. Does not connect to normal runtime or real finance."""
import json,secrets,uuid,time,io,csv,zipfile,hashlib
from pathlib import Path
from datetime import datetime,timedelta,timezone
import httpx
R=Path(__file__).resolve().parents[1];P=R/'backend/.runtime/qa/browser-credentials.json';creds=json.loads(P.read_text());checks=[]
def check(name,passed):
 if not passed:raise AssertionError(name)
 checks.append({'name':name,'passed':True})
def login(person):
 c=httpx.Client(base_url='http://127.0.0.1:18411',trust_env=False,timeout=30);r=c.post('/api/auth/login',json={'username':person['username'],'password':person['password']});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
admin=login(creds)
def send(c,path,body,method='POST',key=None):
 r=c.request(method,'/api'+path,json=body,headers={'X-Idempotency-Key':key or uuid.uuid4().hex});r.raise_for_status();return r.json()
p=send(admin,'/projects',{'code':'QA26-'+secrets.token_hex(3),'name':'嘉元跨链证据（脱敏）'});pid=p['id'];base='/projects/'+pid+'/assurance';people={who:creds['cost25']['people'][{'manager':'pm','reader':'purchase','finance':'finance'}[who]] for who in ['manager','reader','finance']}
for who,role in [('manager','项目经理'),('reader','采购'),('finance','财务')]:send(admin,'/projects/'+pid+'/members',{'account_id':people[who]['id'],'roles':[role],'revision':0},'PUT')
root_account=admin.get('/api/session').json()['account'];send(admin,'/projects/'+pid+'/members',{'account_id':root_account['id'],'roles':['管理员','商务','设计'],'revision':1},'PUT');cs={who:login(x) for who,x in people.items()};pm=cs['manager'];reader=cs['reader'];fin=cs['finance'];ctx={'project_id':pid,'project_code':p['code'],'people':people};creds['assurance26_setup']=ctx;P.write_text(json.dumps(creds));P.chmod(0o600)
def board(who='manager'):
 r=cs[who].get('/api'+base+'/board');r.raise_for_status();return r.json()
def case(eid,who='manager'):return next(x for x in board(who)['exceptions'] if x['id']==eid)
def act(eid,name,**kw):return send(pm,base+'/exceptions/'+eid+'/actions',{'revision':case(eid)['revision'],'action':name,**kw})
def requirement(title):return send(admin,'/projects/'+pid+'/handoff/documents',{'kind':'requirement','body':{'title':title,'summary':'合成跨链验收需求，不是实际项目资料','source':'QA26','attachment_ids':[],'brief_due_at':'2000-01-01T00:00:00+00:00'}})
doc=requirement('跨链异常修复验证');e=next(x for x in board()['exceptions'] if x['object_id']==doc['id']);eid=e['id'];check('重复扫描保留同一活动实例',all(next(x for x in board()['exceptions'] if x['object_id']==doc['id'])['id']==eid for _ in range(3)))
act(eid,'read');act(eid,'remind');check('已读催办不关闭事实异常',case(eid)['state']=='open');r=pm.post('/api'+base+'/exceptions/'+eid+'/actions',json={'revision':case(eid)['revision'],'action':'close'},headers={'X-Idempotency-Key':uuid.uuid4().hex});check('手动关闭无效且接口拒绝',r.status_code==422)
act(eid,'assign',owner_id=people['reader']['id'],reason='合成采购配合商务补交底');check('指派实际有效项目成员',case(eid)['owner_id']==people['reader']['id'] and any(x['id']==eid for x in board('reader')['exceptions']))
r=reader.post('/api'+base+'/exceptions/'+eid+'/actions',json={'revision':case(eid)['revision'],'action':'waive','reason':'越权尝试'},headers={'X-Idempotency-Key':uuid.uuid4().hex});check('普通责任人不能登记豁免',r.status_code==403)
proof_path=R/'backend/.runtime/qa/assurance-approval.md';proof_path.write_text('Synthetic existing approval: waive reminder only; no business release.\n');proof_path.chmod(0o600)
r=pm.post('/api'+base+'/exceptions/'+eid+'/files',files={'file':(proof_path.name,proof_path.read_bytes(),'text/plain')},headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();fid=r.json()['id'];act(eid,'waive',reason='合成批准暂缓提醒，来源仍须修复',approval_no='SYN-QA26',until=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),file_ids=[fid]);check('有原件有期限豁免仍非通过',case(eid)['state']=='waived')
send(admin,'/projects/'+pid+'/handoff/documents/'+doc['id']+'/publish',{'revision':doc['revision'],'recipient_ids':[root_account['id']],'diff_summary':'商务真实发布合成交底以修复事实'});check('来源事实修复自动关闭并保留记录',case(eid)['state']=='resolved' and any(x['action']=='waive' for x in case(eid)['events']))
# Create a private finance error through the real upload/parse/precheck path.
cost='/projects/'+pid+'/cost';profile=send(fin,cost+'/profiles',{'source_system':'SYN-QA26','name':'合成成本映射','subjects':{'6601':'成本'},'wbs':{'W1':'工程'},'key_mode':'id','estimate_policy':'separate','basis':'合成财务确认稳定键及映射'})
from sys import path
path.insert(0,str(R/'backend'))
from app.cost_import import FIELDS
row={'source_id':'PRIVATE1','line_version':'1','project_code':p['code'],'entry_date':'2026-10-15','subject_code':'6601','wbs_code':'W1','kind':'实际','business_id':'PRIVATE-BUS','amount':'9.99','quantity':'1','unit':'','currency':'CNY','tax_basis':'含税'};stream=io.StringIO();writer=csv.writer(stream);writer.writerow(FIELDS.values());writer.writerow([row.get(k,'') for k in FIELDS]);now=datetime.now(timezone.utc).isoformat();meta={'profile_id':profile['id'],'period':'2026-10','currency':'CNY','tax_basis':'含税','mode':'increment','reason':'合成异常隔离验证','exported_at':now,'data_cutoff':'2026-10-31T15:59:59+00:00'}
r=fin.post('/api'+cost+'/batches',data={'meta':json.dumps(meta)},files={'file':('finance-private.csv',stream.getvalue().encode(),'text/csv')},headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();bid=r.json()['id']
def wait_batch(state):
 for _ in range(150):
  r=fin.get('/api'+cost+'/batches/'+bid);r.raise_for_status();b=r.json()
  if b['state']==state:return b
  time.sleep(.1)
 raise AssertionError('后台预检超时')
b=wait_batch('mapping');send(fin,cost+'/batches/'+bid+'/actions',{'revision':b['revision'],'action':'mapping','mapping':FIELDS});wait_batch('invalid');check('财务错误异常对PM及采购不可见',any(x['financial'] for x in board('finance')['exceptions']) and not any(x['financial'] for x in board()['exceptions']+board('reader')['exceptions']))
# Export current project data and check actual files rather than a success label.
key=uuid.uuid4().hex;payload={'confirmed':True,'include_sensitive':False,'reason':'合成本机证据核对'};task=send(pm,base+'/exports',payload,key=key);again=send(pm,base+'/exports',payload,key=key);check('导出重试同任务不重复排队',task['id']==again['id'])
for _ in range(250):
 r=pm.get('/api'+base+'/exports/'+task['id']);r.raise_for_status();t=r.json()
 if t['state']=='ready':break
 if t['state']=='failed':raise AssertionError(t['error'])
 time.sleep(.1)
else:raise AssertionError('导出未生成')
r=pm.get('/api'+base+'/exports/'+task['id']+'/download');r.raise_for_status()
with zipfile.ZipFile(io.BytesIO(r.content)) as z:
 manifest=json.loads(z.read('manifest.json'));objects=json.loads(z.read('objects.json'));check('真实证据包文件哈希全部一致',all(hashlib.sha256(z.read(x['path'])).hexdigest()==x['sha256'] for x in manifest['files']));check('PM导出无财务源行或认证字段',not objects['cost'].get('batches') and not any(x['financial'] for x in objects['exceptions']) and not any(v in z.read('objects.json').decode() for v in ['password_hash','csrf','PRIVATE1']))
check('其他账号不能下载他人的旧证据包',reader.get('/api'+base+'/exports/'+task['id']+'/download').status_code==404)
# A second unfinished item is reserved for browser interaction.
browserdoc=requirement('浏览器异常指派与豁免');browsercase=next(x for x in board()['exceptions'] if x['object_id']==browserdoc['id']);ctx|={'browser_case_id':browsercase['id'],'proof_path':str(proof_path),'finance_batch_id':bid,'export_id':task['id']};creds['assurance26']=ctx;P.write_text(json.dumps(creds));P.chmod(0o600)
E=R/'docs/evidence/阶段2-6';E.mkdir(exist_ok=True,parents=True);(E/'真实业务冒烟.json').write_text(json.dumps({'environment':'18411 local synthetic','checks':checks},ensure_ascii=False,indent=2)+'\n')
print({'checks':len(checks),'browser_fixture_ready':True})
for c in [admin,*cs.values()]:c.close()
