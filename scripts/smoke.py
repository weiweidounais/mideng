"""Real local HTTP checks using explicit synthetic data; never a model smoke log."""
import json
import os
import secrets
import sys
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import httpx

ROOT=Path(__file__).resolve().parents[1]
URL=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:18411'
DATA=ROOT/'backend/.runtime/qa'
DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
private=DATA/'browser-credentials.json'
if private.exists():
    credentials=json.loads(private.read_text())
else:
    credentials={'username':'qa-admin','password':secrets.token_urlsafe(18)}
    fd=os.open(private,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(credentials,f)
checks=[]
def check(label,condition):
    if not condition:raise AssertionError(label)
    checks.append({'check':label,'result':'通过'})

def session(c,username,password):
    r=c.post('/api/auth/login',json={'username':username,'password':password});r.raise_for_status()
    c.headers['X-CSRF-Token']=r.json()['csrf']
    return r.json()['account']

def write(c,method,path,body,key=None):
    return c.request(method,path,json=body,headers={'X-Idempotency-Key':key or str(uuid.uuid4())})

with httpx.Client(base_url=URL,trust_env=False,timeout=15) as admin:
    if admin.get('/api/setup').json()['required']:
        r=admin.post('/api/setup',json=credentials|{'display_name':'测试管理员'});r.raise_for_status()
    session(admin,credentials['username'],credentials['password'])
    suffix=uuid.uuid4().hex[:7]
    body={'code':'QA-'+suffix,'name':'嘉元协同试点 · 脱敏测试'};key=str(uuid.uuid4())
    p=write(admin,'POST','/api/projects',body,key);p.raise_for_status();p=p.json()
    again=write(admin,'POST','/api/projects',body,key)
    check('真实HTTP重复提交返回同一项目',again.json()['id']==p['id'])
    secret_project=write(admin,'POST','/api/projects',{'code':'OTHER-'+suffix,'name':'其他项目 · 隔离检查'});secret_project.raise_for_status()
    user={'username':'qa-'+suffix,'display_name':'测试项目经理','password':secrets.token_urlsafe(18)}
    person=write(admin,'POST','/api/accounts',user);person.raise_for_status();person=person.json()
    membership={'account_id':person['id'],'roles':['项目经理'],'revision':0}
    assigned=write(admin,'PUT',f'/api/projects/{p["id"]}/members',membership);assigned.raise_for_status()
    with httpx.Client(base_url=URL,trust_env=False,timeout=15) as ordinary:
        session(ordinary,user['username'],user['password'])
        visible=ordinary.get('/api/projects').json()
        check('独立账号只收到所属项目',len(visible)==1 and visible[0]['id']==p['id'])
        check('猜测其他项目ID被服务端拒绝',ordinary.get('/api/projects/'+secret_project.json()['id']).status_code==404)
        conflict=write(ordinary,'PATCH','/api/projects/'+p['id'],{'name':'保留的修改','revision':99})
        check('错误revision返回409与当前版本',conflict.status_code==409 and conflict.json()['error']['current_revision']==1)
        check('未授权旧知识及模型入口未挂载',ordinary.get('/api/collaboration/board').status_code==404 and ordinary.get('/api/providers').status_code==404)
        check('运行策略确为模型关闭',ordinary.get('/api/runtime').json()['model_enabled'] is False)
        updated=write(admin,'PUT',f'/api/projects/{p["id"]}/members',membership|{'revision':1,'active':False});updated.raise_for_status()
        check('撤权后同一登录会话立即无法读取项目',ordinary.get('/api/projects/'+p['id']).status_code==404)
    # Leave synthetic manager authorized for the independent-browser validation.
    write(admin,'PUT',f'/api/projects/{p["id"]}/members',membership|{'revision':2}).raise_for_status()
    credentials.update({'business_account':user,'project_id':p['id'],'other_project_id':secret_project.json()['id']})
    private.write_text(json.dumps(credentials));private.chmod(0o600)
    events=admin.get('/api/projects/'+p['id']+'/audit');events.raise_for_status()
    check('审计使用服务端责任账号并关联请求',all(e['actor_id'] and e['request_id'] for e in events.json()))
result={'time':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'environment':URL,'data':'explicit-synthetic','model_enabled':False,'checks':checks,'project_id':p['id']}
output=ROOT/'docs/evidence/阶段2-1/业务冒烟结果.json';output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'checks_passed':len(checks),'evidence':str(output)},ensure_ascii=False))
