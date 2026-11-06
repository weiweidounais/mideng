"""Actual isolated HTTP multi-role workflow, never seeds normal user data."""
from pathlib import Path
from datetime import datetime,timezone
import json,uuid,secrets,httpx,hashlib
R=Path(__file__).resolve().parents[1];P=R/'backend/.runtime/qa/browser-credentials.json';all_creds=json.loads(P.read_text());old=all_creds['handoff22'];pid=old['project_id'];people=old['people'].copy();checks=[]
def check(name,value):
    assert value,name;checks.append({'name':name,'result':'通过'})
def login(u):
    c=httpx.Client(base_url='http://127.0.0.1:18411',trust_env=False,timeout=20);r=c.post('/api/auth/login',json={k:u[k] for k in ['username','password']});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
def write(c,path,b,key=None):
    r=c.post('/api'+path,json=b,headers={'X-Idempotency-Key':key or uuid.uuid4().hex});r.raise_for_status();return r.json()
admin=login(all_creds)
for key,role in [('pm','项目经理'),('quality','质量')]:
    u={'username':'pv2-'+key+'-'+uuid.uuid4().hex[:7],'display_name':'闭环测试'+role,'password':secrets.token_urlsafe(16)}
    person=write(admin,'/accounts',u);u['id']=person['id'];people[key]=u
    r=admin.put('/api/projects/'+pid+'/members',json={'account_id':u['id'],'roles':[role],'revision':0},headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status()
cs={key:login(u) for key,u in people.items()};h='/projects/'+pid+'/handoff';base='/projects/'+pid+'/procurement'
def make_source(suffix):
    d=write(cs['market'],h+'/documents',{'kind':'requirement','body':{'title':'采购闭环需求'+suffix,'summary':'合成材料，验证项目经理与质量、商务责任','source':'脱敏联调'}})
    d=write(cs['biz'],h+'/documents/'+d['id']+'/publish',{'revision':d['revision'],'recipient_ids':[people['design']['id']],'diff_summary':'闭环测试'})
    s=write(cs['design'],h+'/documents',{'kind':'scheme','parent_id':d['id'],'source_version_id':d['versions'][0]['id'],'body':{'title':'采购闭环BOM'+suffix,'notes':'本机合成材料料表','bom':[{'material':'合成管材','spec':'DN100','quantity':'0.3','unit':'米','need_by':'2026-12-01'}]}})
    s=write(cs['design'],h+'/documents/'+s['id']+'/publish',{'revision':s['revision'],'recipient_ids':[people['pm']['id']],'diff_summary':'设计提交指定项目经理'})
    return s['versions'][0]['id']
version=make_source('·HTTP')
payload={'version_id':version,'title':'V2独立账号采购闭环（合成）','note':'项目经理提需求，采购下单后复核，质量待到货','purchase_id':people['purchase']['id'],'quality_id':people['quality']['id'],'commerce_id':people['biz']['id']}
o=write(cs['pm'],base+'/orders',payload,key='v2-smoke-create-'+version)
check('设计确认方案交项目经理，项目经理创建需求',o['revision']==1)
def get(who='pm'):
    r=cs[who].get('/api'+base+'/board');r.raise_for_status();return next(x for x in r.json()['orders'] if x['id']==o['id'])
def action(who,name,**extra):
    global o
    o=write(cs[who],base+'/orders/'+o['id']+'/actions',{'revision':o['revision'],'action':name,**extra});return get(who)
r=cs['purchase'].post('/api'+base+'/orders/'+o['id']+'/actions',json={'revision':o['revision'],'action':'approve_purchase'},headers={'X-Idempotency-Key':uuid.uuid4().hex});check('采购不能代替项目经理复核',r.status_code==403)
action('purchase','accept_purchase');action('purchase','submit_result',result={'supplier':'合成供应商','lines':[{'line_no':1,'quantity':'0.3','eta':'2026-12-01'}]})
check('采购结果回交项目经理',get()['state']=='pm_review')
action('pm','approve_purchase');check('项目经理通过后质量待到货',get()['state']=='quality_wait')
now=datetime.now(timezone.utc).isoformat();action('purchase','arrival',arrival={'line_no':1,'quantity':'0.1','occurred_at':now});check('部分到货不开放整单质量结论',get()['state']=='quality_wait')
action('quality','arrival',arrival={'line_no':1,'quantity':'0.2','occurred_at':now});check('实际足量后开放质量验收',get()['state']=='quality_check')
def upload(who,purpose,content):
    r=cs[who].post('/api'+base+'/orders/'+o['id']+'/files',data={'purpose':purpose},files={'file':(purpose+'.md',content,'text/plain')},headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();return r.json()
report=upload('quality','quality',b'Synthetic material quality report: passed')
action('quality','pass_quality',file_ids=[report['id']]);check('质量确认后交商务归档',get()['state']=='business_archive')
content=b'Synthetic procurement contract; internal QA only';f=upload('biz','archive',content)
action('biz','archive',archive={'contract_no':'QA-PROC-V2','contract_amount':'123.45','tax_basis':'含税','costs':[{'name':'合成材料成本','amount':'100.10'},{'name':'合成运费','amount':'0.20'}],'file_ids':[f['id']]})
check('商务明确归档且成本精确合计',get('biz')['state']=='archived' and get('biz')['archive_total']=='100.30')
check('项目经理看不到采购归档金额或私有原件',get()['archive'] is None and cs['pm'].get('/api'+base+'/files/'+f['id']).status_code==404)
got=cs['biz'].get('/api'+base+'/files/'+f['id']);check('商务下载合同实际字节哈希一致',hashlib.sha256(got.content).hexdigest()==f['sha256'])
browser_version=make_source('·浏览器')
all_creds['procurement_v2']={'project_id':pid,'people':people,'version_id':browser_version};P.write_text(json.dumps(all_creds));P.chmod(0o600)
for c in [admin,*cs.values()]:c.close()
e=R/'docs/evidence/阶段2-2';(e/'采购闭环V2业务冒烟.json').write_text(json.dumps({'time':datetime.now(timezone.utc).isoformat(),'data':'synthetic QA18411 only','checks':checks},ensure_ascii=False,indent=2)+'\n')
print({'actual_http_checks':len(checks),'browser_fixture_ready':True})
