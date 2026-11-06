"""Create a fresh trace-only synthetic QA database, never copy pilot/financial data."""
from pathlib import Path
import os,sys,json,secrets,uuid
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'backend/.runtime/mobile-qa'
DATA.mkdir(mode=0o700,parents=True,exist_ok=True)
if (DATA/'pilot.db').exists():raise SystemExit('隔离库已存在，保留现有数据；请复用credentials.json而勿重复初始化。')
os.environ['PILOT_DATA_DIR']=str(DATA);sys.path.insert(0,str(ROOT/'backend'))
from app.pilot import make_app
from fastapi.testclient import TestClient
app=make_app(worker=False);people={};clients={}
def write(c,path,body,method='POST'):
 r=c.request(method,'/api'+path,json=body,headers={'X-CSRF-Token':c.get('/api/session').json()['csrf'],'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();return r.json()
with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',18411)) as admin:
 password=''.join(str(secrets.randbelow(10)) for _ in range(6));r=admin.post('/api/setup',json={'username':'mobile-admin','display_name':'合成验收管理员','password':password});r.raise_for_status();aid=r.json()['account']['id']
 p=write(admin,'/projects',{'code':'MOBILE-QA33','name':'手机管段验收（仅合成数据）'});pid=p['id'];write(admin,'/projects/'+pid+'/members',{'account_id':aid,'roles':['管理员','市场','商务','设计'],'revision':1},'PUT')
 people['admin']={'username':'mobile-admin','password':password,'id':aid}
 for key,role in [('pm','项目经理'),('factory','工厂'),('site','现场'),('quality','质量')]:
  password=''.join(str(secrets.randbelow(10)) for _ in range(6));u={'username':'mobile-'+key,'display_name':'手机合成'+role,'password':password};person=write(admin,'/accounts',u);people[key]=u|{'id':person['id']};write(admin,'/projects/'+pid+'/members',{'account_id':person['id'],'roles':[role],'revision':0},'PUT');c=TestClient(app,base_url='http://127.0.0.1');r=c.post('/api/auth/login',json={'username':u['username'],'password':password});r.raise_for_status();clients[key]=c
 h='/projects/'+pid+'/handoff';b='/projects/'+pid+'/trace'
 d=write(admin,h+'/documents',{'kind':'requirement','body':{'title':'合成管段扫码采集需求','summary':'非实际项目，仅验证手机流程','source':'合成QA'}});d=write(admin,h+'/documents/'+d['id']+'/publish',{'revision':d['revision'],'recipient_ids':[aid],'diff_summary':'合成需求'})
 s=write(admin,h+'/documents',{'kind':'scheme','parent_id':d['id'],'source_version_id':d['versions'][0]['id'],'body':{'title':'合成管段正式BOM','notes':'不代表真实工艺批准','bom':[{'material':'合成管材','spec':'DN100','quantity':'30','unit':'根','need_by':'2026-12-01'}]}});s=write(admin,h+'/documents/'+s['id']+'/publish',{'revision':s['revision'],'recipient_ids':[people['pm']['id']],'diff_summary':'合成正式依据'})
 t=write(clients['quality'],b+'/templates',{'name':'手机合成工序','scope':'仅QA管段','welding':False,'pressure':False,'basis':'合成验证无焊接/试压，不代表真实批准'})
 o=write(clients['pm'],b+'/orders',{'code':'MOBILE-ORDER','version_id':s['versions'][0]['id'],'factory_id':people['factory']['id'],'site_id':people['site']['id'],'quality_id':people['quality']['id']})
 spools=[write(clients['factory'],b+'/spools',{'code':f'MOBILE-{i+1:03}','order_id':o['id'],'template_id':t['id']}) for i in range(24)]
 credentials={'project_id':pid,'people':people,'spool_id':spools[0]['id'],'template_id':t['id'],'order_id':o['id']};f=DATA/'credentials.json';f.write_text(json.dumps(credentials));f.chmod(0o600)
 (DATA/'synthetic-only.marker').write_text('stage33 trace-only QA; no copied data\n')
 from PIL import Image
 Image.new('RGB',(600,400),'#407d87').save(DATA/'synthetic-photo.jpg');(DATA/'synthetic-report.md').write_text('Synthetic report only; not actual quality evidence.\n')
for c in clients.values():c.close()
print({'prepared':True,'synthetic_spools':24,'credentials_saved_locally':True,'listeners_started':False})
