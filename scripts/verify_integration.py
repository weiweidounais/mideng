"""Portable M2 verification; M3 real models remain an explicit separate gate."""
from pathlib import Path
import subprocess,os,json,secrets,signal,time,sys
ROOT=Path(__file__).resolve().parents[1];E=ROOT/'docs/evidence/整合M2';E.mkdir(parents=True,exist_ok=True);checks=[]
def run(name,cmd,cwd=ROOT,env=None):
    with (E/(name+'.txt')).open('w') as log:
        p=subprocess.run(cmd,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,text=True)
    checks.append({'check':name,'passed':p.returncode==0,'exit_code':p.returncode});print(name, 'PASS' if p.returncode==0 else 'FAIL',flush=True)
    return p.returncode==0
python=str(ROOT/'backend/.venv/bin/python')
run('后端测试',[python,'-m','pytest','-q'],ROOT/'backend')
for name,args in [('前端测试',['test']),('类型检查',['run','typecheck']),('Lint',['run','lint']),('构建',['run','build'])]:run(name,['npm',*args],ROOT/'frontend')
run('源码凭据检查',[python,'scripts/check-secrets.py'])
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
