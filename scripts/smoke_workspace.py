"""Real local synthetic workspace checks; persists only in the isolated QA database."""
from pathlib import Path
import json,uuid,time,httpx
R=Path(__file__).resolve().parents[1];P=R/'backend/.runtime/qa/browser-credentials.json';x=json.loads(P.read_text());data=x['procurement_v2'];pid=data['project_id'];people=data['people'];checks=[]
def login(u):
 c=httpx.Client(base_url='http://127.0.0.1:18411',trust_env=False,timeout=20);r=c.post('/api/auth/login',json={k:u[k] for k in ('username','password')});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
cs={name:login(u) for name,u in people.items()};h='/projects/'+pid+'/handoff';base='/projects/'+pid+'/procurement';w='/projects/'+pid+'/workspace'
def write(who,path,body,method='POST'):
 r=cs[who].request(method,'/api'+path,json=body,headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();return r.json()
def check(name,value):assert value,name;checks.append({'name':name,'result':'通过'})
existing=cs['pm'].get('/api'+w+'/procurement').json()['items']
existing=next((o for o in existing if o['title'].startswith('导航复核QA31-') and o['state']=='pm_review'),None)
if existing:
 o=cs['pm'].get('/api'+w+'/purchase-orders/'+existing['id']).json()['order'];s=cs['pm'].get('/api'+h+'/documents/'+cs['pm'].get('/api'+w+'/purchase-orders/'+o['id']).json()['source']['object_id']).json();d={'id':s['parent_id']}
else:
 label='导航复核QA31-'+uuid.uuid4().hex[:6]
 d=write('market',h+'/documents',{'kind':'requirement','body':{'title':label+'需求','summary':'合成的两种材料数量与需用日期','source':'本机合成验收'}});d=write('biz',h+'/documents/'+d['id']+'/publish',{'revision':d['revision'],'recipient_ids':[people['design']['id']],'diff_summary':'首次合成需求'})
 s=write('design',h+'/documents',{'kind':'scheme','parent_id':d['id'],'source_version_id':d['versions'][0]['id'],'body':{'title':label+'正式方案','notes':'数量和交期分开复核','bom':[{'material':'合成管材','spec':'DN100','quantity':'1','unit':'米','need_by':'2026-12-01'},{'material':'合成连接件','spec':'DN100弯头','quantity':'2','unit':'个','need_by':'2026-12-02'}]}});s=write('design',h+'/documents/'+s['id']+'/publish',{'revision':s['revision'],'recipient_ids':[people['pm']['id']],'diff_summary':'供项目经理核对的正式BOM'})
 o=write('pm',base+'/orders',{'version_id':s['versions'][0]['id'],'title':label+'材料采购','note':'合成数量差异和交期延后代表页','purchase_id':people['purchase']['id'],'quality_id':people['quality']['id'],'commerce_id':people['biz']['id']});o=write('purchase',base+'/orders/'+o['id']+'/actions',{'revision':o['revision'],'action':'accept_purchase'});o=write('purchase',base+'/orders/'+o['id']+'/actions',{'revision':o['revision'],'action':'submit_result','result':{'supplier':'合成供应商','lines':[{'line_no':1,'quantity':'1.2','eta':'2026-12-03'},{'line_no':2,'quantity':'2','eta':'2026-12-02'}],'note':'额外0.2米备料；第一项交期延后，需项目经理明确确认'}})
 o=cs['pm'].get('/api'+w+'/purchase-orders/'+o['id']).json()['order']
for _ in range(50):
 r=cs['pm'].get('/api/workbench').json()
 if any(t['link']['object_id']==o['id'] for t in r['items']):break
 time.sleep(.1)
check('真实持久待办指向当前PM复核采购单',any(t['link']['object_id']==o['id'] and t['link']['state']=='pm_review' for t in r['items']))
loc=cs['pm'].get('/api'+w+'/locate',params={'section':'procurement','object_id':o['id'],'version_id':o['version_id'],'kind':'procurement'});check('对象和正式来源版本可校验定位',loc.status_code==200)
detail=cs['pm'].get('/api'+w+'/purchase-orders/'+o['id']).json();check('数量差异与交期延后逐行准确',detail['comparison'][0]['quantity_changed'] and detail['comparison'][0]['late_eta'] and not detail['comparison'][1]['quantity_changed'])
check('采购摘要不携带BOM和合同金额',all('lines' not in row and 'archive' not in row for row in cs['pm'].get('/api'+w+'/procurement').json()['items']))
check('错误来源版本定位拒绝',cs['pm'].get('/api'+w+'/locate',params={'section':'procurement','object_id':o['id'],'version_id':'wrong-source'}).status_code==404)
check('需求与方案所选上下文包含原件版本',len(cs['pm'].get('/api'+w+'/document-context/'+s['id']).json()['documents'])==2)
x['workspace31']={'project_id':pid,'people':people,'order_id':o['id'],'scheme_id':s['id'],'requirement_id':d['id'],'source_version':o['version_id'],'title':o['title']};P.write_text(json.dumps(x));P.chmod(0o600)
e=R/'docs/evidence/阶段3-1';e.mkdir(parents=True,exist_ok=True);(e/'真实业务冒烟.json').write_text(json.dumps({'environment':'QA18411 synthetic','checks':checks},ensure_ascii=False,indent=2)+'\n')
for c in cs.values():c.close()
print({'checks':len(checks),'browser_fixture_ready':True})
