"""Real synthetic HTTP change flow on QA18411, no normal business writes."""
from pathlib import Path
import json,uuid,time,httpx
R=Path(__file__).resolve().parents[1];P=R/'backend/.runtime/qa/browser-credentials.json';creds=json.loads(P.read_text());data=creds['procurement_v2'];pid=data['project_id'];people=data['people'];checks=[]
def check(name,value):assert value,name;checks.append({'name':name,'result':'通过'})
def login(u):
 c=httpx.Client(base_url='http://127.0.0.1:18411',trust_env=False,timeout=20);r=c.post('/api/auth/login',json={k:u[k] for k in ['username','password']});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
cs={name:login(u) for name,u in people.items()};h='/projects/'+pid+'/handoff';proc='/projects/'+pid+'/procurement';base='/projects/'+pid+'/changes'
def write(who,path,body,method='POST'):
 r=cs[who].request(method,'/api'+path,json=body,headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();return r.json()
def make(suffix):
 d=write('market',h+'/documents',{'kind':'requirement','body':{'title':'变更来源'+suffix,'summary':'合成现行施工约束','source':'合成联调'}})
 d=write('biz',h+'/documents/'+d['id']+'/publish',{'revision':d['revision'],'recipient_ids':[people['design']['id']],'diff_summary':'旧版交底'})
 s=write('design',h+'/documents',{'kind':'scheme','parent_id':d['id'],'source_version_id':d['versions'][0]['id'],'body':{'title':'变更测试BOM'+suffix,'notes':'合成材料','bom':[{'material':'合成管材','spec':'DN100','quantity':'1','unit':'米','need_by':'2026-12-01'}]}})
 s=write('design',h+'/documents/'+s['id']+'/publish',{'revision':s['revision'],'recipient_ids':[people['pm']['id']],'diff_summary':'指定PM'})
 o=write('pm',proc+'/orders',{'version_id':s['versions'][0]['id'],'title':'变更影响采购'+suffix,'note':'采购已下单时不得自动抹除事实','purchase_id':people['purchase']['id'],'quality_id':people['quality']['id'],'commerce_id':people['biz']['id']})
 o=write('purchase',proc+'/orders/'+o['id']+'/actions',{'revision':o['revision'],'action':'accept_purchase'})
 o=write('purchase',proc+'/orders/'+o['id']+'/actions',{'revision':o['revision'],'action':'submit_result','result':{'supplier':'合成供应商','lines':[{'line_no':1,'quantity':'1','eta':'2026-12-01'}]}})
 old=d['versions'][0];d=write('market',h+'/documents/'+d['id']+'/revise',{'revision':d['revision']});d=write('market',h+'/documents/'+d['id'],{'revision':d['revision'],'body':old['body']|{'summary':'新增现场约束，须核对旧采购处置'}},'PATCH');d=write('biz',h+'/documents/'+d['id']+'/publish',{'revision':d['revision'],'recipient_ids':[people['design']['id']],'diff_summary':'新版约束'})
 payload={'title':'现场变更'+suffix,'reason':'正式版本替代需专业核对','old_version_id':old['id'],'new_version_id':d['versions'][0]['id']}
 c=write('pm',base,payload);return c,o,payload
c,o,payload=make('·HTTP')
def get():
 r=cs['pm'].get('/api'+base+'/board');r.raise_for_status();return next(x for x in r.json()['cases'] if x['id']==c['id'])
def action(who,name,**extra):
 current=get();return write(who,base+'/'+c['id']+'/actions',{'revision':current['revision'],'action':name,'version_id':current['current']['id'] if current['current'] else None,**extra})
def upload(who,purpose):
 r=cs[who].post('/api'+base+'/'+c['id']+'/files',data={'purpose':purpose},files={'file':(purpose+'.md',b'Synthetic existing approval or execution evidence; QA only','text/plain')},headers={'X-Idempotency-Key':uuid.uuid4().hex});r.raise_for_status();return r.json()['id']
def prepare():
 for category,who in [('technical','design'),('cost','biz'),('schedule','pm'),('quality','quality')]:action(who,'impact',category=category,has_impact=False,reason='合成专业核对：无额外影响，允许按凭据处置')
 f=upload('pm','approval');action('pm','approval',approval_no='SYNTHETIC-CHANGE',reason='登记既有合成批准凭据',file_ids=[f]);action('pm','publish',recipient_ids=get()['required_recipient_ids'])
prepare();check('四类独立专业结论及原件后冻结发布',get()['current']['number']==1)
r=cs['pm'].post('/api'+proc+'/orders/'+o['id']+'/actions',json={'revision':o['revision'],'action':'approve_purchase'},headers={'X-Idempotency-Key':uuid.uuid4().hex});check('未完成变更确认处置的旧采购被拦截',r.status_code==409)
for _ in range(50):
 if all(r['delivered_at'] for r in get()['current']['receipts']):break
 time.sleep(.1)
check('送达依据实际持久站内待办',all(r['delivered_at'] for r in get()['current']['receipts']))
for who in ['pm','design','quality','biz']:action(who,'ack')
r=cs['pm'].post('/api'+base+'/'+c['id']+'/actions',json={'revision':get()['revision'],'action':'request_close','version_id':get()['current']['id']},headers={'X-Idempotency-Key':uuid.uuid4().hex});check('一位采购未确认时关闭被拦截',r.status_code==409)
action('purchase','ack')
for t in get()['current']['body']['targets']:
 action('pm','plan',target_key=t['key'],decision='continue',reason='合成既有批准允许继续使用')
 who=next(k for k,v in people.items() if v['id']==t['owner_id']);f=upload(who,'execution');action(who,'execute',target_key=t['key'],reason='实际处置已核对，关联原件',file_ids=[f]);action('pm','verify',target_key=t['key'])
action('pm','request_close');action('pm','close');check('逐对象证据核对齐全后PM关闭',get()['state']=='closed')
o=write('pm',proc+'/orders/'+o['id']+'/actions',{'revision':o['revision'],'action':'approve_purchase'})
r=cs['pm'].get('/api'+proc+'/board');order=next(x for x in r.json()['orders'] if x['id']==o['id']);check('旧采购凭批准继续但原BOM版本和下单结果保留',order['result']['supplier']=='合成供应商' and not order['needs_review'])
old=get()['current']['id'];action('pm','revise',replacement=payload|{'reason':'补充发布范围，须重新确认'});prepare();check('修订新发布版不沿用旧接收确认',get()['current']['id']!=old and not any(r['confirmed_at'] for r in get()['current']['receipts']))
browser_case,browser_order,browser_payload=make('·浏览器')
creds['change_v3']={'project_id':pid,'people':people,'case_id':browser_case['id'],'order_id':browser_order['id'],'payload':browser_payload};P.write_text(json.dumps(creds));P.chmod(0o600)
e=R/'docs/evidence/阶段2-3';e.mkdir(parents=True,exist_ok=True);(e/'真实业务冒烟.json').write_text(json.dumps({'environment':'QA18411 synthetic','checks':checks},ensure_ascii=False,indent=2)+'\n')
for client in cs.values():client.close()
print({'checks':len(checks),'browser_fixture_ready':True})
