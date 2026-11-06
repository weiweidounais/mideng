"""Advisory local 10-user / 10000-row HTTP measurement; synthetic fixture seeding is outside timing."""
import os,sys,json,subprocess,secrets,sqlite3,time,uuid,platform,math
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import httpx
R=Path(__file__).resolve().parents[1];OUT=R/'docs/evidence/阶段2-6/建议负载实测.json';DATA=R/'backend/.runtime/qa'/('perf26-'+secrets.token_hex(4));DATA.mkdir(mode=0o700);env=os.environ.copy();env['RESTART_CHECK_DIR']=str(DATA);python=str(R/'backend/.venv/bin/python');samples=[]
def hook(action,*args):return subprocess.check_output([python,str(R/'scripts/restart_check.py'),action,*args],env=env,cwd=R,text=True,stderr=(DATA/'hook-errors.log').open('a')).strip().splitlines()[-1]
try:
 pid=int(hook('start'));ids=hook('write','synthetic-performance-'+secrets.token_hex(8)).split(':');project_id=ids[0];state=json.loads((DATA/'hook.json').read_text());url='http://127.0.0.1:'+str(state['port'])
 def login(person):
  c=httpx.Client(base_url=url,trust_env=False,timeout=90);r=c.post('/api/auth/login',json=person);r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
 root=login({'username':'restart-admin','password':state['password']})
 def post(c,path,body,method='POST'):
  r=c.request(method,'/api'+path,json=body,headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();return r.json()
 people=[]
 for i in range(10):
  person={'username':'perf-'+str(i),'password':secrets.token_urlsafe(14)};a=post(root,'/accounts',person|{'display_name':'合成负载账号'+str(i)});post(root,'/projects/'+project_id+'/members',{'account_id':a['id'],'roles':['商务','设计','项目经理','工厂','现场','质量','采购','财务'],'revision':0},'PUT');people.append(person)
 # Valid FK-linked source rows, constructed solely for load; never a quality or business-completion sample.
 db=sqlite3.connect(DATA/'runtime/pilot.db');db.execute('pragma foreign_keys=on');actor_id=db.execute('select id from pilot_accounts where username=?',('restart-admin',)).fetchone()[0];contract_id=ids[4];now=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat();before_rows=db.execute('select count(*) from handoff_rows').fetchone()[0];before_trace=db.execute('select count(*) from trace_records').fetchone()[0]
 n_material=5000-before_rows;n_trace=10000-5000-before_trace
 db.executemany('INSERT INTO handoff_rows(id,project_id,contract_id,line_no,material,spec,quantity,unit,need_by,state,eta,blocked,note,revision,created_by,updated_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',[(uuid.uuid4().hex,project_id,contract_id,i+2,'合成负载料行','DN-SYN','1','米','2026-12-01','pending',None,False,'仅性能样本',1,actor_id,actor_id,now,now) for i in range(n_material)])
 order_id=db.execute('select id from trace_orders limit 1').fetchone()[0];template_id=db.execute('select id from trace_templates limit 1').fetchone()[0];spool_id=uuid.uuid4().hex;db.execute('insert into trace_spools(id,project_id,order_id,template_id,code,revision,state,parents,created_by,created_at,updated_at) values(?,?,?,?,?,?,?,?,?,?,?)',(spool_id,project_id,order_id,template_id,'PERF-ONLY',1,'registered','[]',actor_id,now,now))
 db.executemany('insert into trace_records(id,project_id,spool_id,kind,data,file_ids,source,occurred_at,received_at,actor_id,corrects_id) values(?,?,?,?,?,?,?,?,?,?,?)',[(uuid.uuid4().hex,project_id,spool_id,'fabrication',json.dumps({'equipment':'SYN','description':'仅性能构造履历'+str(i)}),'[]','manual',now,now,actor_id,None) for i in range(n_trace)]);db.commit();counts={t:db.execute('select count(*) from '+t).fetchone()[0] for t in ['handoff_rows','trace_records','trace_spools']};assert counts['handoff_rows']+counts['trace_records']==10000;assert db.execute('pragma foreign_key_check').fetchall()==[];db.close()
 clients=[login(p) for p in people]
 for c in clients:c.get('/api/projects/'+project_id).raise_for_status()
 def user(index):
  c=clients[index];result=[]
  for j in range(2):
   for name,path,body in [('项目读取','/api/projects/'+project_id,None),('BOM交接查询','/api/projects/'+project_id+'/handoff/board',None),('管段履历查询','/api/projects/'+project_id+'/trace/board',None),('独立需求草稿写入','/api/projects/'+project_id+'/handoff/documents',{'kind':'requirement','body':{'title':'合成负载草稿','summary':'仅负载构造，不是业务交付','source':'synthetic benchmark','attachment_ids':[]}})]:
    start=time.perf_counter();status=0;error=None
    try:
     r=c.request('POST' if body else 'GET',path,json=body,headers={'X-Idempotency-Key':uuid.uuid4().hex} if body else {});status=r.status_code;r.raise_for_status()
    except Exception as e:error=type(e).__name__
    result.append({'operation':name,'seconds':round(time.perf_counter()-start,6),'status':status,'error':error})
  return result
 start=time.perf_counter()
 with ThreadPoolExecutor(max_workers=10) as pool:
  for result in pool.map(user,range(10)):samples.extend(result)
 elapsed=time.perf_counter()-start;stats=[]
 for name in dict.fromkeys(x['operation'] for x in samples):
  values=sorted(x['seconds'] for x in samples if x['operation']==name);errors=sum(x['error'] is not None for x in samples if x['operation']==name);target=3 if '写入' in name else 2;p95=values[math.ceil(len(values)*.95)-1];stats.append({'operation':name,'requests':len(values),'p95_seconds':p95,'max_seconds':max(values),'errors':errors,'error_rate':errors/len(values),'suggested_p95_seconds':target,'within_suggested_comparison':p95<=target and errors==0})
 report={'classification':'建议负载，M1目标未冻结，不构成部署/性能验收通过','environment':{'platform':platform.platform(),'python':platform.python_version(),'cpu_count':os.cpu_count(),'storage':'local SQLite WAL, single app worker, model disabled'},'concurrent_distinct_accounts':10,'fixture_counts':counts,'seeded_synthetic_rows_outside_timing':n_material+n_trace,'total_material_and_trace_rows':10000,'fixture_boundary':'额外料行/履历由隔离脚本构造，外键有效；不作质量放行、完整率或实际业务样本','p95_method':'nearest rank, ceil(0.95*N), per-operation 20 requests','elapsed_seconds':round(elapsed,3),'statistics':stats,'samples':samples};OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:report[k] for k in ['concurrent_distinct_accounts','total_material_and_trace_rows','statistics']},ensure_ascii=False))
 for c in [root,*clients]:c.close()
finally:
 hook('stop')
