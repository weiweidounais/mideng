"""Actual local HTTP chain, explicitly synthetic and independent from user data."""
import hashlib,json,os,secrets,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];URL=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:18411'
private=ROOT/'backend/.runtime/qa/browser-credentials.json';credentials=json.loads(private.read_text())
checks=[]
def check(name,ok):
    if not ok:raise AssertionError(name)
    checks.append({'name':name,'result':'通过'})
def login(user):
    c=httpx.Client(base_url=URL,trust_env=False,timeout=20)
    r=c.post('/api/auth/login',json={k:user[k] for k in ['username','password']});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c

def write(c,method,path,body,key=None):
    r=c.request(method,path,json=body,headers={'X-Idempotency-Key':key or str(uuid.uuid4())})
    r.raise_for_status();return r.json()
admin=login(credentials);suffix=uuid.uuid4().hex[:7]
p=write(admin,'POST','/api/projects',{'code':'QA22-'+suffix,'name':'嘉元一期 · 需求采购联调（脱敏）'})
people={};clients={}
for key,role in [('market','市场'),('biz','商务'),('design','设计'),('purchase','采购')]:
    user={'username':'h22-'+key+'-'+suffix,'password':secrets.token_urlsafe(15),'display_name':'测试'+role}
    person=write(admin,'POST','/api/accounts',user)
    write(admin,'PUT','/api/projects/'+p['id']+'/members',{'account_id':person['id'],'roles':[role],'revision':0})
    people[key]=user|{'id':person['id']};clients[key]=login(user)
base='/api/projects/'+p['id']+'/handoff'
def post(who,path,data,key=None):return write(clients[who],'POST',base+path,data,key)
def patch(who,path,data):return write(clients[who],'PATCH',base+path,data)
content='嘉元试点：仅为合成联调原件，不含真实经营数据。'.encode()
r=clients['market'].post(base+'/files',data={'kind':'requirement'},files={'file':('脱敏交底.md',content,'text/plain')},headers={'X-Idempotency-Key':str(uuid.uuid4())});r.raise_for_status();f=r.json()
d=post('market','/documents',{'kind':'requirement','body':{'title':'预制管材交底','summary':'采用确认版本交接，先试点0.3米','source':'合成甲方交底记录','constraints':'材料和规格一致','attachment_ids':[f['id']]}})
check('采购不能读取未发布需求草稿',clients['purchase'].get(base+'/documents/'+d['id']).status_code==404)
key=str(uuid.uuid4());publish={'revision':d['revision'],'recipient_ids':[people['design']['id']],'diff_summary':'首次正式交底'}
d=post('biz','/documents/'+d['id']+'/publish',publish,key);same=post('biz','/documents/'+d['id']+'/publish',publish,key)
check('重复发布返回同一正式版本',d['versions'][0]['id']==same['versions'][0]['id'])
check('正式原件跨授权账号下载哈希一致',hashlib.sha256(clients['purchase'].get(base+'/files/'+f['id']).content).hexdigest()==f['sha256'])
v1=d['versions'][0]
s=post('design','/documents',{'kind':'scheme','parent_id':d['id'],'source_version_id':v1['id'],'body':{'title':'DN100预制管材方案','notes':'按正式需求交付BOM并核对数量单位','risks':'以指定版为准','bom':[{'material':'预制管材','spec':'DN100','quantity':'0.3','unit':'米','need_by':'2026-12-01'}]}})
s=post('design','/documents/'+s['id']+'/publish',{'revision':s['revision'],'recipient_ids':[people['purchase']['id']],'diff_summary':'首次方案与BOM冻结'})
contract_data={'version_id':s['versions'][0]['id'],'recipient_id':people['purchase']['id'],'deliverable':'DN100方案与BOM交付','quality_rule':'核对版本、规格、数量/单位、需用日期及原件','require_arrival':True}
c=post('design','/contracts',contract_data)
def action(who,c,name,reason=''):
    return post(who,'/contracts/'+c['id']+'/actions',{'revision':c['revision'],'action':name,'reason':reason})
c=action('design',c,'issue');c=action('design',c,'submit');c=action('purchase',c,'return','请补充交付说明并重新核对')
check('退回保留轮次并回到待交付',c['state']=='pending' and c['return_count']==1)
c=action('design',c,'submit');c=action('purchase',c,'accept','已核对交付质量')
b=clients['purchase'].get(base+'/board').json();row=next(x for x in b['rows'] if x['contract_id']==c['id'])
row=patch('purchase','/rows/'+row['id'],{'revision':row['revision'],'state':'ordered','eta':'2026-12-01'})
now=datetime.now(timezone.utc).isoformat();key=str(uuid.uuid4());arrival={'revision':row['revision'],'quantity':'0.1','occurred_at':now}
row=post('purchase','/rows/'+row['id']+'/arrivals',arrival,key);duplicate=post('purchase','/rows/'+row['id']+'/arrivals',arrival,key)
check('重复到货不重复累加且不足量不完成',duplicate['arrived']=='0.1' and row['state']=='ordered')
row=post('purchase','/rows/'+row['id']+'/arrivals',{'revision':row['revision'],'quantity':'0.2','occurred_at':now})
check('十进制到货精确累计0.3',row['arrived']=='0.3' and row['state']=='arrived')
c=action('purchase',c,'close','交付验收与全量到货均已确认');check('满足关闭条件后显式关闭',c['state']=='closed')
old=post('design','/contracts',contract_data|{'deliverable':'旧来源交接，待复核'})
d=post('market','/documents/'+d['id']+'/revise',{'revision':d['revision']})
d=patch('market','/documents/'+d['id'],{'revision':d['revision'],'body':v1['body']|{'summary':'新增约束：下游按新版复核'}})
d=post('biz','/documents/'+d['id']+'/publish',{'revision':d['revision'],'recipient_ids':[people['design']['id']],'diff_summary':'合成客户约束修订'})
check('新旧正式需求各自保留',len(d['versions'])==2 and d['versions'][1]['body']['summary']==v1['body']['summary'])
r=clients['design'].post(base+'/contracts/'+old['id']+'/actions',json={'revision':old['revision'],'action':'issue'},headers={'X-Idempotency-Key':str(uuid.uuid4())})
check('旧来源交接被服务端拦截',r.status_code==409)
board=clients['design'].get(base+'/board').json();check('升版后方案显示需复核',next(x for x in board['documents'] if x['id']==s['id'])['needs_review'])
credentials['handoff22']={'project_id':p['id'],'people':people,'requirement_id':d['id'],'scheme_id':s['id'],'contract_id':c['id']}
private.write_text(json.dumps(credentials));private.chmod(0o600)
for client in [admin,*clients.values()]:client.close()
result={'environment':URL,'data':'explicit-synthetic','model_enabled':False,'checks':checks,'project_id':p['id'],'time':datetime.now(timezone.utc).isoformat()}
(ROOT/'docs/evidence/阶段2-2/业务冒烟结果.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'passed':len(checks),'project_id':p['id']},ensure_ascii=False))
