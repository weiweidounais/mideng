"""Real HTTP financial QA; all accounts and source data are synthetic and local."""
import json,secrets,uuid,csv,io,time
from pathlib import Path
from datetime import datetime,timezone
import httpx,openpyxl
R=Path(__file__).resolve().parents[1];P=R/'backend/.runtime/qa/browser-credentials.json';creds=json.loads(P.read_text());checks=[]
FIELDS={'source_id':'源明细ID','line_version':'行版本','project_code':'项目编码','entry_date':'凭证日期','subject_code':'原科目','wbs_code':'原WBS','kind':'类型','business_id':'事项编码','amount':'金额','quantity':'数量','unit':'单位','currency':'币种','tax_basis':'税口径','document_no':'凭证号','document_line':'凭证行号','related_source':'关联源系统','related_period':'关联期间','related_id':'关联源ID','related_version':'关联行版本','note':'说明'}
def login(person):
 c=httpx.Client(base_url='http://127.0.0.1:18411',trust_env=False,timeout=20);r=c.post('/api/auth/login',json={'username':person['username'],'password':person['password']});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
def send(c,path,body,method='POST'):
 r=c.request(method,'/api'+path,json=body,headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();return r.json()
admin=login(creds);pw=secrets.token_urlsafe(14);person=send(admin,'/accounts',{'username':'qa25-finance-'+secrets.token_hex(3),'display_name':'成本测试财务','password':pw});person['password']=pw
people={'finance':person,'pm':creds['trace24']['people']['pm'],'purchase':creds['trace24']['people']['purchase']};project=send(admin,'/projects',{'code':'QA25-'+secrets.token_hex(3),'name':'嘉元成本月结（脱敏）'});pid=project['id'];base='/projects/'+pid+'/cost'
for who,role in [('finance','财务'),('pm','项目经理'),('purchase','采购')]:send(admin,'/projects/'+pid+'/members',{'account_id':people[who]['id'],'roles':[role],'revision':0},'PUT')
creds['cost25_setup']={'project_id':pid,'people':people};P.write_text(json.dumps(creds));P.chmod(0o600)
cs={who:login(p) for who,p in people.items()};f=cs['finance']
def write(path,body):return send(f,base+path,body)
def check(name,value):
 if not value:raise AssertionError(name)
 checks.append({'name':name,'passed':True})
def board(who='finance'):
 r=cs[who].get('/api'+base+'/board');r.raise_for_status();return r.json()
profile=write('/profiles',{'name':'QA已确认映射','source_system':'SYN-QA25','subjects':{'6601':'项目成本'},'wbs':{'W1':'试点WBS'},'key_mode':'id','estimate_policy':'separate','basis':'合成财务明确确认稳定源ID、科目与WBS对应'})
now=datetime.now(timezone.utc).isoformat();meta={'profile_id':profile['id'],'period':'2026-10','currency':'CNY','tax_basis':'含税','mode':'increment','replace_ids':[],'reason':'合成财务源核对','exported_at':now,'data_cutoff':'2026-10-31T15:59:59+00:00'}
def row(id,value,kind='实际',**extra):return {'source_id':id,'line_version':'1','project_code':project['code'],'entry_date':'2026-10-15','subject_code':'6601','wbs_code':'W1','kind':kind,'business_id':'BUS-'+id,'amount':value,'quantity':'1','unit':'笔','currency':'CNY','tax_basis':'含税',**extra}
def csvdata(rows):
 stream=io.StringIO();w=csv.writer(stream);w.writerow(FIELDS.values())
 for r in rows:w.writerow([r.get(k,'') for k in FIELDS])
 return ('\ufeff'+stream.getvalue()).encode()
def upload(rows,name='source.csv',xlsx=False,**extra):
 if xlsx:
  book=openpyxl.Workbook();sheet=book.active;sheet.append(list(FIELDS.values()))
  for r in rows:sheet.append([r.get(k,'') for k in FIELDS])
  stream=io.BytesIO();book.save(stream);raw=stream.getvalue()
 else:raw=csvdata(rows)
 r=f.post('/api'+base+'/batches',data={'meta':json.dumps(meta|extra)},files={'file':(name,raw,'application/octet-stream')},headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();return r.json()
def batch(b):
 r=f.get('/api'+base+'/batches/'+b['id']);r.raise_for_status();return r.json()
def wait(b,state):
 for _ in range(120):
  v=batch(b)
  if v['state']==state:return v
  if v['state']=='invalid' and state!='invalid':raise AssertionError(v['errors'])
  time.sleep(.1)
 raise AssertionError('后台任务未完成')
def act(b,action,**kw):return write('/batches/'+b['id']+'/actions',{'revision':batch(b)['revision'],'action':action,**kw})
def checked(rows,expected='ready',**kw):
 b=upload(rows,**kw);wait(b,'mapping');act(b,'mapping',mapping=FIELDS);wait(b,expected);return b
bad=checked([row('R1','0.10'),row('R2','0.20',unit='')],expected='invalid');check('缺单位逐行报错且整批未入账',batch(bad)['errors'][0]['row']==3 and not board()['snapshots']);act(bad,'withdraw',reason='错误源表由财务撤回，保留原件')
rows=[row('R1','0.10'),row('R2','0.20'),row('PAY','5.00','付款'),row('ORD','1.00','承诺'),row('INV','0.30','发票')];first=checked(rows);act(first,'commit',confirmed=True,reason='财务核对来源/确定金额及去重差异');repeat=upload(rows);check('同源文件同范围重传返回原批次',repeat['id']==first['id'])
updated=[row('R1','0.15',line_version='2'),row('R2','0.25',line_version='2'),row('PAY','5.00','付款'),row('ORD','1.00','承诺'),row('INV','0.40','发票',line_version='2')];replace=checked(updated,name='cumulative.xlsx',xlsx=True,mode='replace',replace_ids=[first['id']],reason='明确累计表替换指定旧范围');act(replace,'commit',confirmed=True,reason='财务确认累计表新行版及替换范围');check('真实xlsx替换后保留旧批次',batch(first)['state']=='replaced')
r=f.post('/api'+base+'/evidence',files={'file':('synthetic-finance-approval.md',b'Synthetic approved budget and comparable revenue evidence; QA only','text/plain')},headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();evidence=r.json()['id']
write('/budgets',{'currency':'CNY','tax_basis':'含税','kind':'baseline','amount':'0','approval_no':'SYN-BUDGET-ZERO','basis':'合成已确认零预算基线，用于N/A验证','file_ids':[evidence]})
close_body={'period':'2026-10','currency':'CNY','tax_basis':'含税','control_total':'0.40','control_basis':'会计实际加待分摊的已确认源控制范围','reason':'合成月结'}
cl=write('/closes',close_body)
def close_get(cl):return next(c for c in board()['closes'] if c['id']==cl['id'])
def ca(cl,action,**kw):return write('/closes/'+cl['id']+'/actions',{'revision':close_get(cl)['revision'],'action':action,**kw})
r=f.post('/api'+base+'/closes/'+cl['id']+'/actions',json={'revision':cl['revision'],'action':'submit_review'},headers={'X-Idempotency-Key':uuid.uuid4().hex});check('未配置公司日历不能发布月结',r.status_code==409);ca(cl,'cancel',reason='配置日历后重新核对')
cal=write('/calendars',{'name':'合成公司工作日历','start':'2026-11-01','end':'2026-11-15','workdays':['2026-11-03','2026-11-04','2026-11-05'],'basis':'明确1/2非工作，3/4/5工作，非真实公司排班'})
cl=write('/closes',close_body|{'calendar_id':cal['id']});ca(cl,'submit_review');ca(cl,'publish',confirmed=True,reason='财务核对合成来源/控制/口径后发布');snap=board()['snapshots'][0];check('精确实际0.40与付款/承诺/发票分列',snap['body']['actual_accounting']=='0.40' and snap['body']['payment']=='5.00' and snap['body']['commitment']=='1.00');check('预算0不算偏差率，收入未确认不算毛利',snap['body']['variance_rate'] is None and snap['body']['gross_margin'] is None);check('公司第3工作日截止按上海转UTC',snap['body']['deadline']=='2026-11-05T15:59:59+00:00')
late=checked([row('LATE','0.10')]);act(late,'commit',confirmed=True,reason='迟到的合成增量');correct=write('/closes',close_body|{'calendar_id':cal['id'],'control_total':'0.50','correction_of':snap['id'],'revenue':'2.00','revenue_comparable':True,'revenue_basis':'同币种同税口径合成财务确认','revenue_file_ids':[evidence],'reason':'迟到源表更正，旧快照保留'});ca(correct,'submit_review');ca(correct,'publish',confirmed=True,reason='合成财务确认更正版');published=board()['snapshots'];check('更正后旧快照及新版本差异保留',len(published)==2 and published[0]['body']['actual_accounting']=='0.50' and published[1]['body']['actual_accounting']=='0.40');check('可比确认收入后才计算毛利',published[0]['body']['gross_margin']=='1.50')
pm=board('pm');purchase=board('purchase');check('PM仅发布汇总，采购无成本明细',len(pm['snapshots'])==2 and not pm['batches'] and 'line_ids' not in pm['snapshots'][0]['body'] and not purchase['snapshots']);check('PM猜源文件ID无法下载',cs['pm'].get('/api'+base+'/files/'+batch(replace)['source_id']).status_code==403)
q=R/'backend/.runtime/qa';bad_path=q/'cost-browser-invalid.csv';good_path=q/'cost-browser-valid.csv';bad_path.write_bytes(csvdata([row('BROWSER1','0.20'),row('BROWSER2','0.30',unit='')]));good_path.write_bytes(csvdata([row('BROWSER1','0.20'),row('BROWSER2','0.30')]));creds['cost25']={'project_id':pid,'people':people,'profile_id':profile['id'],'calendar_id':cal['id'],'evidence_id':evidence,'latest_snapshot_id':published[0]['id'],'bad_file':str(bad_path),'good_file':str(good_path)};P.write_text(json.dumps(creds));P.chmod(0o600)
e=R/'docs/evidence/阶段2-5';e.mkdir(exist_ok=True,parents=True);(e/'真实业务冒烟.json').write_text(json.dumps({'environment':'QA18411 synthetic','checks':checks},ensure_ascii=False,indent=2)+'\n')
for c in cs.values():c.close()
admin.close();print({'checks':len(checks),'browser_fixture_ready':True})
