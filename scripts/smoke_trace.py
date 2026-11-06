"""Actual local QA HTTP chain; private credentials never enter evidence output."""
import json,secrets,uuid
from pathlib import Path
from datetime import datetime,timezone
import httpx
R=Path(__file__).resolve().parents[1];P=R/'backend/.runtime/qa/browser-credentials.json';creds=json.loads(P.read_text());people=dict(creds['change_v3']['people']);cs={};checks=[]
def client(person):
 c=httpx.Client(base_url='http://127.0.0.1:18411',trust_env=False,timeout=15);r=c.post('/api/auth/login',json={'username':person['username'],'password':person['password']});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
admin=client(creds)
def send(c,path,body,method='POST'):
 r=c.request(method,'/api'+path,json=body,headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();return r.json()
for who in ['factory','site']:
 pw=secrets.token_urlsafe(14);person=send(admin,'/accounts',{'username':'qa24-'+who+'-'+secrets.token_hex(3),'display_name':'管段测试'+('工厂' if who=='factory' else '现场'),'password':pw});people[who]=person|{'password':pw}
p=send(admin,'/projects',{'code':'QA24-'+secrets.token_hex(3),'name':'嘉元管段追溯（脱敏）'});pid=p['id']
for who,r in [('pm','项目经理'),('factory','工厂'),('site','现场'),('quality','质量'),('biz','商务'),('design','设计'),('market','市场'),('purchase','采购')]:
 send(admin,'/projects/'+pid+'/members',{'account_id':people[who]['id'],'roles':[r],'revision':0},'PUT');cs[who]=client(people[who])
base='/projects/'+pid+'/trace';h='/projects/'+pid+'/handoff'
def write(who,path,body):return send(cs[who],path,body)
def check(name,value):
 if not value:raise AssertionError(name)
 checks.append({'name':name,'passed':True})
req=write('market',h+'/documents',{'kind':'requirement','body':{'title':'管段QA需求','summary':'合成管段追溯验证','source':'本机脱敏'}});req=write('biz',h+'/documents/'+req['id']+'/publish',{'revision':req['revision'],'recipient_ids':[people['design']['id']],'diff_summary':'合成交底'})
scheme=write('design',h+'/documents',{'kind':'scheme','parent_id':req['id'],'source_version_id':req['versions'][0]['id'],'body':{'title':'管段QA正式BOM','notes':'合成图纸/BOM，实际模板另由质量确认','bom':[{'material':'合成管材','spec':'DN100','quantity':'2','unit':'根','need_by':'2026-12-01'}]}});scheme=write('design',h+'/documents/'+scheme['id']+'/publish',{'revision':scheme['revision'],'recipient_ids':[people['pm']['id']],'diff_summary':'合成预制依据'})
template=write('quality',base+'/templates',{'name':'焊接与试压合成模板','scope':'QA管段；不代表企业真实工艺批准','welding':True,'pressure':True,'basis':'QA指定质量岗位明确确认两类工序均适用'})
order=write('pm',base+'/orders',{'code':'FAB-QA24','version_id':scheme['versions'][0]['id'],'factory_id':people['factory']['id'],'site_id':people['site']['id'],'quality_id':people['quality']['id']})
s=write('factory',base+'/spools',{'code':'SP-HTTP-24','order_id':order['id'],'template_id':template['id']})
def board():
 r=cs['pm'].get('/api'+base+'/board');r.raise_for_status();return r.json()
def current():return next(x for x in board()['spools'] if x['id']==s['id'])
def act(who,name,**kw):return write(who,base+'/spools/'+s['id']+'/actions',{'revision':current()['revision'],'action':name,**kw})
def upload(who,name='evidence.md',raw=b'Synthetic trace report; not actual quality evidence'):
 r=cs[who].post('/api'+base+'/spools/'+s['id']+'/files',files={'file':(name,raw,'application/json' if name.endswith('.json') else 'text/plain')},headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();return r.json()['id']
def record(who,kind,data,**kw):return write(who,base+'/spools/'+s['id']+'/records',{'revision':current()['revision'],'kind':kind,'data':data,'occurred_at':datetime.now(timezone.utc).isoformat(),**kw})
def inspect(passed):return act('quality','inspect',passed=passed,reason='合成质量结果，仅验证门槛',file_ids=[upload('quality')],weld_ids=[w['id'] for w in current()['welds']])
r=cs['factory'].post('/api'+base+'/spools/'+s['id']+'/actions',json={'revision':1,'action':'start'},headers={'X-Idempotency-Key':uuid.uuid4().hex});check('无材料证书不能开工',r.status_code==409)
record('factory','material',{'batch':'SYN-MATERIAL-24'},file_ids=[upload('factory')]);act('factory','start');record('factory','weld',{'weld_code':'WELD-HTTP-24','welder_code':'SYN-QUAL-24','consumable_batch':'SYN-WIRE-24','equipment':'SYN-EQ-24'})
when=datetime.now(timezone.utc).isoformat();raw={'kind':'fabrication','data':{'equipment':'SYN-EQ-24','description':'从实际JSON原件导入合成工序'},'occurred_at':when};fid=upload('factory','actual-import.json',json.dumps(raw).encode());write('factory',base+'/spools/'+s['id']+'/records',raw|{'revision':current()['revision'],'source':'template_import','file_ids':[fid]});check('实际模板导入保留JSON原件与来源',any(r['source']=='template_import' for r in current()['records']))
act('factory','submit_inspection');inspect(False);r=cs['factory'].post('/api'+base+'/spools/'+s['id']+'/actions',json={'revision':current()['revision'],'action':'ship'},headers={'X-Idempotency-Key':uuid.uuid4().hex});check('质量不合格无法直接发运',r.status_code==409)
record('factory','repair',{'description':'合成返修实际记录'},file_ids=[upload('factory')]);act('factory','submit_inspection');inspect(True);act('factory','ship',location='合成工厂发运位',reference='SYN-SHIP-24',occurred_at=datetime.now(timezone.utc).isoformat());act('site','install',location='合成安装区域',reference='SYN-INSTALL-24',occurred_at=datetime.now(timezone.utc).isoformat());record('site','pressure',{'equipment':'SYN-PRESSURE-24','description':'合成试压过程'},file_ids=[upload('site')]);act('quality','confirm_pressure',passed=True,reason='质量核对试压合成报告',file_ids=[upload('quality')]);act('quality','complete',reason='合成适用工序履历核对齐全');check('指定工厂现场质量走通履历完成',current()['state']=='completed');check('返修与初检复检旧判定追加保留',len([r for r in current()['records'] if r['kind']=='inspection'])==2)
label1=act('factory','label');label2=act('factory','label');check('重打同定位符不产生新管段',label1['locator']==label2['locator'] and len(board()['spools'])==1)
with httpx.Client(base_url='http://127.0.0.1:18411',trust_env=False) as anonymous:check('二维码查询及扫码定位仍需登录',anonymous.get('/api'+base+'/spools/'+s['id']+'/qr').status_code==401 and anonymous.get('/api/spool-locator/'+s['id']).status_code==401)
check('完成分母正确且在制另列',board()['metrics']['completed_total']==1 and board()['metrics']['completed_valid']==1)
check('普通岗位响应隐藏焊工资格代码','SYN-QUAL-24' not in cs['biz'].get('/api'+base+'/board').text)
browser=write('factory',base+'/spools',{'code':'SP-BROWSER-24','order_id':order['id'],'template_id':template['id']});creds['trace24']={'project_id':pid,'people':people,'spool_id':browser['id'],'http_spool_id':s['id'],'order_id':order['id'],'template_id':template['id']};P.write_text(json.dumps(creds));P.chmod(0o600)
e=R/'docs/evidence/阶段2-4';e.mkdir(exist_ok=True,parents=True);(e/'真实业务冒烟.json').write_text(json.dumps({'environment':'QA18411 synthetic','checks':checks},ensure_ascii=False,indent=2)+'\n')
for c in cs.values():c.close()
admin.close();print({'checks':len(checks),'browser_fixture_ready':True})
