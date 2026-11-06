"""One-project synthetic HTTP rehearsal for phase3-4; no normal runtime access."""
from pathlib import Path
from datetime import datetime,timezone
import os,sys,json,secrets,uuid,time,subprocess,io,csv,hashlib,zipfile
import httpx
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'backend/.runtime/release-qa';CREDENTIALS=DATA/'credentials.json';URL='http://127.0.0.1:18431';CHECKS=[];clients={}
sys.path.insert(0,str(ROOT/'backend'))
from app.cost_import import FIELDS

def check(name,condition):
 if not condition:raise AssertionError(name)
 CHECKS.append({'name':name,'passed':True})
def login(u):
 c=httpx.Client(base_url=URL,trust_env=False,timeout=30);r=c.post('/api/auth/login',json={k:u[k] for k in ['username','password']});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
def write(who,path,body,method='POST',key=None):
 r=clients[who].request(method,'/api'+path,json=body,headers={'X-Idempotency-Key':key or uuid.uuid4().hex});r.raise_for_status();return r.json()
def read(who,path):
 for marker,collection in [('/procurement/orders/','orders'),('/changes/','cases')]:
  if marker in path:
   prefix,tail=path.split(marker,1)
   if '/' not in tail and tail!='board':
    board=read(who,prefix+('/procurement/board' if collection=='orders' else '/changes/board'))
    return next(x for x in board[collection] if x['id']==tail)
 r=clients[who].get('/api'+path);r.raise_for_status();return r.json()
def upload(who,path,name='synthetic-proof.md',purpose=None):
 raw=b'Synthetic release rehearsal evidence, no real business or approvals.';r=clients[who].post('/api'+path,data={'purpose':purpose} if purpose else {},files={'file':(name,raw,'text/plain')},headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();return r.json()['id']
def save():
 CREDENTIALS.write_text(json.dumps(ctx));CREDENTIALS.chmod(0o600)
def publish_report():
 path=ROOT/'docs/evidence/整合M2/真实四链检查.json';old=json.loads(path.read_text()) if path.exists() else {'environment':'isolated loopback18431 release-qa; synthetic only','checks':[]};old['checks']+=CHECKS;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(old,ensure_ascii=False,indent=2)+'\n');print({'mode':mode,'checks':len(CHECKS)})
mode=sys.argv[1] if len(sys.argv)>1 else 'prepare'
if mode=='prepare':
 DATA.mkdir(mode=0o700,parents=True,exist_ok=True)
 if CREDENTIALS.exists():raise SystemExit('已有验收库，保留；使用后续模式继续，勿重复初始化。')
 env=os.environ.copy();env['PILOT_DATA_DIR']=str(DATA);env.pop('PILOT_MOBILE_QA_HOST',None)
 import socket
 with socket.socket() as sock:sock.bind(('127.0.0.1',18431))
 with (DATA/'server.log').open('ab') as log:
  process=subprocess.Popen([str(ROOT/'backend/.venv/bin/python'),'-m','uvicorn','app.pilot:app','--host','127.0.0.1','--port','18431','--no-access-log'],cwd=ROOT/'backend',env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
 for _ in range(100):
  try:httpx.get(URL+'/api/health',trust_env=False,timeout=1).raise_for_status();break
  except httpx.HTTPError:time.sleep(.1)
 else:raise RuntimeError('隔离验收服务未就绪')
 admin={'username':'release-admin','password':secrets.token_urlsafe(16)}
 with httpx.Client(base_url=URL,trust_env=False) as c:r=c.post('/api/setup',json=admin|{'display_name':'合成联调管理员'});r.raise_for_status()
 clients['admin']=login(admin);p=write('admin','/projects',{'code':'QA34','name':'密灯四链验收（同一合成项目）'});ctx={'server_pid':process.pid,'project_id':p['id'],'project_code':p['code'],'people':{'admin':admin}};pid=p['id'];base='/projects/'+pid
 for key,role in [('market','市场'),('biz','商务'),('design','设计'),('pm','项目经理'),('purchase','采购'),('quality','质量'),('factory','工厂'),('site','现场'),('finance','财务'),('observer','采购'),('outsider','市场')]:
  u={'username':'release-'+key,'display_name':'联调'+role+('只读' if key=='observer' else ''),'password':secrets.token_urlsafe(16)};a=write('admin','/accounts',u);ctx['people'][key]=u|{'id':a['id']};clients[key]=login(u)
  if key!='outsider':write('admin',base+'/members',{'account_id':a['id'],'roles':[role],'revision':0},'PUT')
 people=ctx['people'];h=base+'/handoff';proc=base+'/procurement';trace=base+'/trace';cost=base+'/cost'
 d=write('market',h+'/documents',{'kind':'requirement','body':{'title':'QA34跨岗位需求','summary':'同一合成项目贯穿四链','source':'合成验收，不代表真实批准'}});d=write('biz',h+'/documents/'+d['id']+'/publish',{'revision':d['revision'],'recipient_ids':[people['design']['id']],'diff_summary':'合成需求正式交底'})
 s=write('design',h+'/documents',{'kind':'scheme','parent_id':d['id'],'source_version_id':d['versions'][0]['id'],'body':{'title':'QA34正式BOM','notes':'合成预制/采购来源','bom':[{'material':'合成管材','spec':'DN100','quantity':'0.3','unit':'米','need_by':'2026-12-01'}]}});s=write('design',h+'/documents/'+s['id']+'/publish',{'revision':s['revision'],'recipient_ids':[people['pm']['id']],'diff_summary':'设计交PM提出采购需求'})
 o=write('pm',proc+'/orders',{'version_id':s['versions'][0]['id'],'title':'QA34材料采购需求','note':'先下单复核约定交期，再等实际到货','purchase_id':people['purchase']['id'],'quality_id':people['quality']['id'],'commerce_id':people['biz']['id']})
 for action,body in [('accept_purchase',{}),('submit_result',{'result':{'supplier':'QA34合成供应商','lines':[{'line_no':1,'quantity':'0.3','eta':'2026-12-01'}]}})]:o=write('purchase',proc+'/orders/'+o['id']+'/actions',{'revision':o['revision'],'action':action,**body})
 template=write('quality',trace+'/templates',{'name':'QA34焊接/试压模板','scope':'仅合成管段','welding':True,'pressure':True,'basis':'本机QA质量确认工序适用'})
 order=write('pm',trace+'/orders',{'code':'FAB-QA34','version_id':s['versions'][0]['id'],'factory_id':people['factory']['id'],'site_id':people['site']['id'],'quality_id':people['quality']['id']});spool=write('factory',trace+'/spools',{'code':'SP-QA34','order_id':order['id'],'template_id':template['id']})
 def act(name):
  global spool
  spool=write('factory',trace+'/spools/'+spool['id']+'/actions',{'revision':spool['revision'],'action':name})
 def record(kind,data,files=[]):
  global spool
  spool=write('factory',trace+'/spools/'+spool['id']+'/records',{'revision':spool['revision'],'kind':kind,'data':data,'file_ids':files,'occurred_at':datetime.now(timezone.utc).isoformat()})
 record('material',{'batch':'QA34-MAT'},[upload('factory',trace+'/spools/'+spool['id']+'/files')]);act('start');record('weld',{'weld_code':'QA34-W1','welder_code':'QA34-QUAL','consumable_batch':'QA34-WIRE','equipment':'QA34-EQ'});record('fabrication',{'equipment':'QA34-EQ','description':'合成预制完成'});act('submit_inspection')
 report=upload('quality',trace+'/spools/'+spool['id']+'/files')
 profile=write('finance',cost+'/profiles',{'name':'QA34已确认映射','source_system':'SYN-QA34','subjects':{'6601':'工程成本'},'wbs':{'W1':'QA34工程'},'basis':'合成财务确认，不代企业真实口径','estimate_policy':'separate'})
 proof=upload('finance',cost+'/evidence');write('finance',cost+'/budgets',{'currency':'CNY','tax_basis':'含税','kind':'baseline','amount':'120.00','approval_no':'SYN-QA34','basis':'合成已批准预算','file_ids':[proof]});cal=write('finance',cost+'/calendars',{'name':'QA34合成公司日历','start':'2026-11-01','end':'2026-11-15','workdays':['2026-11-03','2026-11-04','2026-11-05'],'basis':'明确合成工作日，非公司真实日历'})
 def csv_file(name,bad=False):
  stream=io.StringIO();writer=csv.writer(stream);writer.writerow(FIELDS.values())
  for source,kind,value in [('ACT','实际','100.30'),('COMMIT','承诺','123.45'),('PAY','付款','90.00'),('INVOICE','发票','100.30')]:
   row={'source_id':source,'line_version':'1','project_code':'QA34','entry_date':'2026-10-15','subject_code':'6601','wbs_code':'W1','kind':kind,'business_id':'BUS-'+source,'amount':value,'quantity':'1','unit':'' if bad else '笔','currency':'CNY','tax_basis':'含税'};writer.writerow([row.get(k,'') for k in FIELDS])
  file=DATA/name;file.write_text('\ufeff'+stream.getvalue());file.chmod(0o600);return str(file)
 ctx|={'requirement_id':d['id'],'old_requirement_version':d['versions'][0]['id'],'scheme_id':s['id'],'scheme_version':s['versions'][0]['id'],'purchase_id':o['id'],'spool_id':spool['id'],'template_id':template['id'],'trace_order_id':order['id'],'trace_report_id':report,'profile_id':profile['id'],'calendar_id':cal['id'],'finance_evidence_id':proof,'good_csv':csv_file('good-cost.csv'),'bad_csv':csv_file('bad-cost.csv',True)}
 (DATA/'quality-report.md').write_text('Synthetic QA34 material inspection evidence.\n');(DATA/'contract.md').write_text('Synthetic QA34 purchase contract, not actual approval.\n');save();check('同一合成项目已准备正式来源/待PM复核采购/待质检管段/财务基础',True)
else:
 ctx=json.loads(CREDENTIALS.read_text());clients={who:login(u) for who,u in ctx['people'].items()};pid=ctx['project_id'];base='/projects/'+pid;people=ctx['people'];h=base+'/handoff';proc=base+'/procurement';trace=base+'/trace';cost=base+'/cost'
 if mode=='after_pm':
  o=read('pm',proc+'/orders/'+ctx['purchase_id']);check('浏览器PM确认已到质量待到货',o['state']=='quality_wait')
  for who,q in [('purchase','0.1'),('quality','0.2')]:o=write(who,proc+'/orders/'+o['id']+'/actions',{'revision':o['revision'],'action':'arrival','arrival':{'line_no':1,'quantity':q,'occurred_at':datetime.now(timezone.utc).isoformat()}})
  ctx['purchase_quality_file']=upload('quality',proc+'/orders/'+o['id']+'/files',purpose='quality');save();check('实际分批0.1+0.2到货后才准备质量判定',True)
 elif mode=='after_inspection':
  sid=ctx['spool_id'];s=read('factory',trace+'/workspace/spools/'+sid);check('浏览器质量检测已放行',s['state']=='ready')
  for who,action in [('factory','ship'),('site','install')]:
   write(who,trace+'/spools/'+sid+'/actions',{'revision':s['revision'],'action':action,'location':'QA34合成位置','reference':'SYN-'+action,'occurred_at':datetime.now(timezone.utc).isoformat()});s=read(who,trace+'/workspace/spools/'+sid)
  fid=upload('site',trace+'/spools/'+sid+'/files');write('site',trace+'/spools/'+sid+'/records',{'revision':s['revision'],'kind':'pressure','data':{'equipment':'QA34-PRESSURE','description':'合成现场试压'},'file_ids':[fid],'occurred_at':datetime.now(timezone.utc).isoformat()});ctx['pressure_report_id']=upload('quality',trace+'/spools/'+sid+'/files','synthetic-pressure-report.md');save();check('指定工厂发运/现场安装并提交实际试压',True)
 elif mode=='change':
  p=read('biz',proc+'/orders/'+ctx['purchase_id']);s=read('quality',trace+'/workspace/spools/'+ctx['spool_id']);check('采购已归档且管段履历已完成',p['state']=='archived' and s['state']=='completed')
  check('商务采购成本未被自动变成F6会计入账',not read('finance',cost+'/workspace')['batches'])
  doc=read('market',h+'/documents/'+ctx['requirement_id']);doc=write('market',h+'/documents/'+doc['id']+'/revise',{'revision':doc['revision']});body=doc['draft']|{'summary':'QA34新正式要求，原采购及管段事实仍保留'};doc=write('market',h+'/documents/'+doc['id'],{'revision':doc['revision'],'body':body},'PATCH');doc=write('biz',h+'/documents/'+doc['id']+'/publish',{'revision':doc['revision'],'recipient_ids':[people['design']['id']],'diff_summary':'核对已执行对象的来源变更'})
  c=write('pm',base+'/changes',{'title':'QA34来源变更','reason':'已执行对象须按批准保留及处置','old_version_id':ctx['old_requirement_version'],'new_version_id':doc['versions'][0]['id']});ctx['change_id']=c['id']
  for category,who in [('technical','design'),('cost','biz'),('schedule','pm'),('quality','quality')]:
   c=write(who,base+'/changes/'+c['id']+'/actions',{'revision':c['revision'],'action':'impact','category':category,'has_impact':False,'reason':'合成专业核对：已有事实保留，按批准继续'})
  fid=upload('pm',base+'/changes/'+c['id']+'/files',purpose='approval');write('pm',base+'/changes/'+c['id']+'/actions',{'revision':c['revision'],'action':'approval','approval_no':'SYN-QA34','reason':'登记合成已取得批准原件','file_ids':[fid]});save();check('四专业和批准原件已准备，留浏览器发布',True)
 elif mode=='change_execute':
  change=base+'/changes/'+ctx['change_id']
  def current():return read('pm',change)
  c=current();check('浏览器变更已发布',c['current'] is not None)
  for _ in range(100):
   c=current()
   if all(x['delivered_at'] for x in c['current']['receipts']):break
   time.sleep(.1)
  for aid in c['required_recipient_ids']:
   who=next(k for k,u in people.items() if u.get('id')==aid);c=current();write(who,change+'/actions',{'revision':c['revision'],'version_id':c['current']['id'],'action':'ack'})
  for target in current()['current']['body']['targets']:
   c=current();write('pm',change+'/actions',{'revision':c['revision'],'version_id':c['current']['id'],'action':'plan','target_key':target['key'],'decision':'continue','reason':'按既有批准保留原事实并继续'})
   who=next(k for k,u in people.items() if u.get('id')==target['owner_id']);fid=upload(who,change+'/files',purpose='execution');c=current();write(who,change+'/actions',{'revision':c['revision'],'version_id':c['current']['id'],'action':'execute','target_key':target['key'],'file_ids':[fid],'reason':'实际核对合成对象并留证'});c=current();write('pm',change+'/actions',{'revision':c['revision'],'version_id':c['current']['id'],'action':'verify','target_key':target['key']})
  c=current();write('pm',change+'/actions',{'revision':c['revision'],'version_id':c['current']['id'],'action':'request_close'});check('本人确认与逐对象证据完成，留浏览器PM关闭',True)
 elif mode=='close_ready':
  c=write('finance',cost+'/closes',{'period':'2026-10','currency':'CNY','tax_basis':'含税','calendar_id':ctx['calendar_id'],'control_total':'100.30','control_basis':'合成会计实际控制总额','reason':'QA34合成月结'});c=write('finance',cost+'/closes/'+c['id']+'/actions',{'revision':c['revision'],'action':'submit_review'});ctx['close_id']=c['id'];save();check('实际入账后月结提交确认，留浏览器明确发布',True)
 elif mode=='verify':
  p=read('biz',proc+'/orders/'+ctx['purchase_id']);s=read('quality',trace+'/workspace/spools/'+ctx['spool_id']);c=read('pm',base+'/changes/'+ctx['change_id']);f=read('finance',cost+'/workspace');pm=read('pm',cost+'/workspace');observer=read('observer',cost+'/workspace');check('四链同一项目终态一致',p['state']=='archived' and s['state']=='completed' and c['state']=='closed' and len(f['snapshots'])==1);check('采购归档100.30与会计实际100.30来源各自独立',p['archive_total']=='100.30' and f['snapshots'][0]['body']['actual_accounting']=='100.30');check('错误源批次保留且未整批入账',any(b['state']=='withdrawn' and b['errors_count']==4 for b in f['batches']));check('完成管段与采购经变更处置后来源允许继续',s['source_ok'] and not p['needs_review']);check('付款承诺分列不并入会计实际',f['snapshots'][0]['body']['payment']=='90.00' and f['snapshots'][0]['body']['commitment']=='123.45');check('PM仅发布汇总且普通岗位无成本数据',not pm['batches'] and not pm['files'] and len(pm['snapshots'])==1 and not observer['snapshots']);check('普通岗位焊工资格脱敏','QA34-QUAL' not in json.dumps(read('observer',trace+'/board')));check('外项目身份拒绝访问',clients['outsider'].get('/api'+base).status_code==404)
  exports=read('pm',base+'/assurance/board')['exports'];ready=next(x for x in exports if x['state']=='ready');raw=clients['pm'].get('/api'+base+'/assurance/exports/'+ready['id']+'/download');raw.raise_for_status()
  with zipfile.ZipFile(io.BytesIO(raw.content)) as z:
   manifest=json.loads(z.read('manifest.json'));check('实际证据包所有文件哈希一致',all(hashlib.sha256(z.read(x['path'])).hexdigest()==x['sha256'] for x in manifest['files']));objects=json.loads(z.read('objects.json'));check('PM包无财务源批次或认证字段',not objects['cost'].get('batches') and 'password_hash' not in z.read('objects.json').decode())
  check('其他账号不能猜包下载',clients['observer'].get('/api'+base+'/assurance/exports/'+ready['id']+'/download').status_code==404);ctx['export_id']=ready['id'];save()
 elif mode=='revoke_observer':
  member=write('admin',base+'/members',{'account_id':people['observer']['id'],'roles':['采购'],'revision':ctx.get('observer_revision',1),'active':False},'PUT');ctx['observer_revision']=member['revision'];save();check('撤销成员后旧会话立即拒绝项目',clients['observer'].get('/api'+base).status_code==404)
 elif mode=='restore_observer':
  member=write('admin',base+'/members',{'account_id':people['observer']['id'],'roles':['采购'],'revision':ctx['observer_revision'],'active':True},'PUT');ctx['observer_revision']=member['revision'];save();check('恢复合成成员后重新按当前权限读取',clients['observer'].get('/api'+base).status_code==200)
 elif mode=='exception_prepare':
  doc=write('market',h+'/documents',{'kind':'requirement','body':{'title':'QA34异常来源核对','summary':'合成待交底，用于并发与事实修复','source':'合成验收','brief_due_at':'2000-01-01T00:00:00+00:00'}});board=read('pm',base+'/assurance/board');item=next(x for x in board['exceptions'] if x['object_id']==doc['id']);ctx['exception_id']=item['id'];ctx['exception_document_id']=doc['id'];save();check('真实逾期待交底事实生成异常',item['state']=='open')
 elif mode=='exception_concurrent':
  item=next(x for x in read('pm',base+'/assurance/board')['exceptions'] if x['id']==ctx['exception_id']);write('pm',base+'/assurance/exceptions/'+item['id']+'/actions',{'revision':item['revision'],'action':'read'});check('独立请求先更新异常版本用于CAS核对',True)
 elif mode=='exception_verify':
  item=next(x for x in read('pm',base+'/assurance/board')['exceptions'] if x['id']==ctx['exception_id']);check('业务来源发布后异常按事实自动关闭',item['state']=='resolved');check('并发后指派与原历史事件均保留',item['owner_id']==people['purchase']['id'] and any(e['action']=='assign' for e in item['events']))
 elif mode=='finance_revoke':
  b=next(x for x in read('finance',cost+'/workspace')['batches'] if x['state']=='committed');key='qa34-sensitive-export-revoke';task=write('finance',base+'/assurance/exports',{'confirmed':True,'include_sensitive':True,'reason':'合成财务撤权与旧包权限复核'},key=key)
  for _ in range(150):
   task=read('finance',base+'/assurance/exports/'+task['id'])
   if task['state']=='ready':break
   time.sleep(.1)
  check('合成财务证据包实际生成后再撤权',task['state']=='ready')
  m=write('admin',base+'/members',{'account_id':people['finance']['id'],'roles':['财务'],'revision':1,'active':False},'PUT')
  check('撤权后已知财务源文件拒绝',clients['finance'].get('/api'+cost+'/files/'+b['source_id']).status_code in {403,404});check('撤权后旧请求结果回查拒绝',clients['finance'].get('/api/requests/'+key).status_code==404);check('撤权后本人旧敏感证据包拒绝',clients['finance'].get('/api'+base+'/assurance/exports/'+task['id']+'/download').status_code==404)
  write('admin',base+'/members',{'account_id':people['finance']['id'],'roles':['财务'],'revision':m['revision'],'active':True},'PUT');check('恢复后权限重新核验可读源文件',clients['finance'].get('/api'+cost+'/files/'+b['source_id']).status_code==200)
 else:raise SystemExit('未知验证模式')
publish_report()
for client in clients.values():client.close()
