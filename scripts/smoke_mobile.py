"""Exercise trace projections and native-photo originals over actual isolated HTTP."""
from pathlib import Path
from datetime import datetime,timezone
import json,uuid,hashlib,httpx
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'backend/.runtime/mobile-qa';cred=json.loads((DATA/'credentials.json').read_text());pid=cred['project_id'];base='/projects/'+pid+'/trace';cs={};checks=[]
for role,u in cred['people'].items():
 c=httpx.Client(base_url='http://127.0.0.1:18411',trust_env=False,timeout=20);r=c.post('/api/auth/login',json={k:u[k] for k in ['username','password']});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];cs[role]=c
def read(who,path,**params):
 r=cs[who].get('/api'+base+path,params=params);r.raise_for_status();return r.json()
def post(who,path,body,key=None):
 r=cs[who].post('/api'+base+path,json=body,headers={'X-Idempotency-Key':key or uuid.uuid4().hex});r.raise_for_status();return r.json()
def check(name,passed):assert passed,name;checks.append({'name':name,'passed':True})
a=read('factory','/workspace');b=read('factory','/workspace',page=2);check('24件管段20+4分页且无全历史',a['total']==24 and len(a['items'])==20 and len(b['items'])==4 and all('records' not in s for s in a['items']))
s=post('factory','/spools',{'code':'DESKTOP-'+uuid.uuid4().hex[:8],'order_id':cred['order_id'],'template_id':cred['template_id']});sid=s['id']
def current():return read('factory','/workspace/spools/'+sid)
def action(who,action,**kw):return post(who,'/spools/'+sid+'/actions',{'revision':current()['revision'],'action':action,**kw})
def upload(who,name):
 raw=(DATA/name).read_bytes();r=cs[who].post('/api'+base+'/spools/'+sid+'/files',files={'file':(name,raw,'image/jpeg' if name.endswith('.jpg') else 'text/plain')},headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();f=r.json();check('原件哈希和受控读回一致',f['sha256']==hashlib.sha256(raw).hexdigest() and cs[who].get('/api'+base+'/files/'+f['id']).content==raw);return f['id']
def record(kind,data,**kw):return post('factory','/spools/'+sid+'/records',{'revision':current()['revision'],'kind':kind,'data':data,'occurred_at':datetime.now(timezone.utc).isoformat(),**kw})
r=cs['factory'].post('/api'+base+'/spools/'+sid+'/actions',json={'revision':current()['revision'],'action':'start'},headers={'X-Idempotency-Key':uuid.uuid4().hex});check('缺材料证书不能开工',r.status_code==409)
f=upload('factory','synthetic-photo.jpg');check('照片受控inline预览',cs['factory'].get('/api'+base+'/files/'+f+'?preview=true').headers['content-disposition'].startswith('inline'))
record('material',{'batch':'SYN33-MAT'},file_ids=[f]);action('factory','start');record('fabrication',{'equipment':'SYN33-EQ','description':'合成预制完成'});action('factory','submit_inspection')
action('quality','inspect',passed=True,reason='仅合成技术判定',file_ids=[upload('quality','synthetic-report.md')],weld_ids=[]);action('factory','ship',location='合成发运位置',reference='SYN33-SHIP',occurred_at=datetime.now(timezone.utc).isoformat());action('site','install',location='合成安装位置',reference='SYN33-INSTALL',occurred_at=datetime.now(timezone.utc).isoformat());action('quality','complete',reason='质量核对非适用焊接和试压及全部合成记录')
d=current();check('指定三岗位完成实际HTTP工序链',d['state']=='completed' and not d['missing']);check('详情保留来源但不传整段历史',d['source_document_id'] and d['source_version_id'] and d['records']==d['events']==d['files']==[])
h=read('quality','/workspace/spools/'+sid+'/history',kind='records',revision=d['revision']);check('分页事实保留发生接收时间及原件',len(h['items'])>=5 and all(x['occurred_at'] and x['received_at'] for x in h['items']) and any(x['attachments'] for x in h['items']))
with httpx.Client(base_url='http://127.0.0.1:18411',trust_env=False) as anon:check('二维码和扫码定位不能绕过登录',anon.get('/api'+base+'/spools/'+sid+'/qr').status_code==401 and anon.get('/api/spool-locator/'+sid).status_code==401)
cred['http_spool_id']=sid;(DATA/'credentials.json').write_text(json.dumps(cred));(DATA/'credentials.json').chmod(0o600)
out=ROOT/'docs/evidence/阶段3-3/真实业务检查.json';out.write_text(json.dumps({'environment':'loopback18411 isolated synthetic mobile QA','checks':checks},ensure_ascii=False,indent=2)+'\n')
for c in cs.values():c.close()
print({'checks':len(checks),'phone_fixture_preserved':True})
