"""Portable M2 verification; M3 real models remain an explicit separate gate."""
from pathlib import Path
import subprocess,os,json,secrets,signal,time,sys
ROOT=Path(__file__).resolve().parents[1];E=Path(os.environ.get('MIDENG_VERIFY_EVIDENCE',ROOT/'docs/evidence/整合M2'));E.mkdir(parents=True,exist_ok=True);checks=[]
def run(name,cmd,cwd=ROOT,env=None):
    with (E/(name+'.txt')).open('w') as log:
        p=subprocess.run(cmd,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,text=True)
    checks.append({'check':name,'passed':p.returncode==0,'exit_code':p.returncode,'cwd':str(cwd),'command':cmd});print(name, 'PASS' if p.returncode==0 else 'FAIL',flush=True)
    return p.returncode==0
python=str(ROOT/'backend/.venv/bin/python')
run('后端测试',[python,'-m','pytest','-q','-o','junit_family=xunit1','--junitxml='+str(E/'后端测试结果.xml')],ROOT/'backend')
# Use the actual HTTP-test observations, not a prefilled acceptance table.
try:
    import hashlib,xml.etree.ElementTree as ET
    fixture=ROOT/'backend/tests/fixtures/knowledge_acceptance_v1.json';spec=json.loads(fixture.read_text());sha=hashlib.sha256(fixture.read_bytes()).hexdigest();observed={}
    for case in ET.parse(E/'后端测试结果.xml').iter('testcase'):
        props={p.get('name'):p.get('value') for p in case.findall('./properties/property')}
        if 'case_id' in props:
            observed[props['case_id']]={'passed':not any(case.find(tag) is not None for tag in ['failure','error','skipped']) and props.get('fixture_sha256')==sha,'actual':json.loads(props.get('observed','{}'))}
    rows=[{'id':case['id'],'category':category,'expected':case,**observed.get(case['id'],{'passed':False,'actual':{'error':'case not executed'}})} for category in ['retrieval','rules'] for case in spec[category]]
    fixed_ok=all(row['passed'] for row in rows) and len(rows)==len(observed)
    (E/'固定用例结果.json').write_text(json.dumps({'version':spec['version'],'fixture_sha256':sha,'passed':sum(row['passed'] for row in rows),'total':len(rows),'failed_ids':[row['id'] for row in rows if not row['passed']],'cases':rows,'scope':spec['scope']},ensure_ascii=False,indent=2))
except Exception as error:
    fixed_ok=False;(E/'固定用例结果.json').write_text(json.dumps({'error':type(error).__name__+': '+str(error),'passed':0}))
checks.append({'check':'固定用例验收','passed':fixed_ok});print('固定用例验收','PASS' if fixed_ok else 'FAIL',flush=True)
for name,args in [('前端测试',['test']),('类型检查',['run','typecheck']),('Lint',['run','lint']),('构建',['run','build'])]:run(name,['npm',*args],ROOT/'frontend')
run('演示测试',['npm','run','test:demo'],ROOT/'frontend')
run('模型关闭策略',[python,'-c',"from app.pilot_policy import read_policy; p=read_policy(); assert p['model_enabled'] is False and p['decision']=='Q3=A' and p['application']=='app.pilot:app'; print('Validated Q3=A: model runtime disabled; no real model calls')"],ROOT/'backend')
run('源码凭据检查',[python,'scripts/check-secrets.py'])
scanner=os.environ.get('GITLEAKS_BIN')
if scanner:
    run('源码历史Gitleaks',[scanner,'git','.', '--log-opts=--all','--redact=100','--no-banner'])
    run('构建产物Gitleaks',[scanner,'dir','frontend/dist','--redact=100','--no-banner'])
    import shutil
    staging=ROOT/'backend/.runtime/verification-source-scan'/secrets.token_hex(8);staging.mkdir(parents=True)
    changed=subprocess.check_output(['git','diff','--name-only','-z'],cwd=ROOT).split(b'\0')
    changed+=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=ROOT).split(b'\0')
    for entry in set(changed):
        if not entry:continue
        rel=Path(os.fsdecode(entry));file=ROOT/rel
        if file.is_file() and not file.is_symlink():
            target=staging/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,target)
    run('本轮改动Gitleaks',[scanner,'dir',str(staging),'--redact=100','--no-banner'])
private=ROOT/'backend/.runtime/integration-recovery'/('run-'+secrets.token_hex(8));private.mkdir(parents=True,exist_ok=True,mode=0o700);env=os.environ.copy();env['RESTART_CHECK_DIR']=str(private)
hook=[python,str(ROOT/'scripts/restart_check.py')];ok=False
try:
    old=subprocess.check_output([*hook,'start'],cwd=ROOT,env=env,text=True).strip();nonce=secrets.token_hex(20)
    ids=subprocess.check_output([*hook,'write',nonce],cwd=ROOT,env=env,text=True).strip()
    command=subprocess.check_output(['ps','-p',old,'-o','command='],text=True)
    assert 'app.pilot:app' in command and python in command
    os.kill(int(old),signal.SIGKILL)
    for _ in range(40):
        r=subprocess.run(['ps','-p',old,'-o','stat='],capture_output=True,text=True)
        if r.returncode or r.stdout.strip().startswith('Z'):break
        time.sleep(.1)
    new=subprocess.check_output([*hook,'start'],cwd=ROOT,env=env,text=True).strip()
    value=subprocess.check_output([*hook,'read',ids],cwd=ROOT,env=env,text=True).strip()
    ok=value==nonce and old!=new
    (E/'重启恢复.txt').write_text(json.dumps({'old_pid':int(old),'new_pid':int(new),'nonce_exact':value==nonce,'four_chains_and_bundle_restore':ok},ensure_ascii=False,indent=2))
except Exception as error:
    (E/'重启恢复.txt').write_text(type(error).__name__+': '+str(error))
finally:subprocess.run([*hook,'stop'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL)
checks.append({'check':'实际强杀与四链全包恢复','passed':ok});print('实际强杀与四链全包恢复','PASS' if ok else 'FAIL',flush=True)
result={'milestone':'M2','checks':checks,'real_model_gate':'本轮按用户2026-11-06裁决不连接模型；API已预留，真实模型效果留后续独立验收','all_passed':all(x['passed'] for x in checks)}
(E/'自检结果.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));sys.exit(0 if result['all_passed'] else 1)
