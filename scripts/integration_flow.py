"""Fresh real-HTTP four-chain rehearsal on isolated 18421; no normal data writes."""
from pathlib import Path
import json,subprocess,sys,time,io,hashlib
from datetime import datetime,timezone
OUT=Path(__file__).resolve().parents[1];SCRIPT=OUT/'scripts/integration_qa.py'
ns={'__file__':str(SCRIPT)}
exec(SCRIPT.read_text().split("mode=sys.argv")[0],ns)
def bind():
    ctx=json.loads((OUT/'backend/.runtime/release-qa/credentials.json').read_text())
    ns.update(ctx=ctx,clients={who:ns['login'](u) for who,u in ctx['people'].items()},mode='http-driver')
    return ctx
ctx=bind();read=ns['read'];write=ns['write'];upload=ns['upload'];check=ns['check'];pid=ctx['project_id'];base='/projects/'+pid;proc=base+'/procurement';trace=base+'/trace';cost=base+'/cost'
def mode(name):
    subprocess.run([sys.executable,str(SCRIPT),name],check=True)
    global ctx
    for c in ns['clients'].values():c.close()
    ctx=bind()
def paction(action,who,**kw):
    o=read(who,proc+'/orders/'+ctx['purchase_id']);return write(who,proc+'/orders/'+o['id']+'/actions',{'revision':o['revision'],'action':action,**kw})
if '--resume-close' not in sys.argv:
    if '--resume-after-proc' not in sys.argv:
        paction('approve_purchase','pm');mode('after_pm')
        paction('pass_quality','quality',file_ids=[ctx['purchase_quality_file']])
        fid=upload('biz',proc+'/orders/'+ctx['purchase_id']+'/files','contract.md','archive')
        paction('archive','biz',archive={'contract_no':'SYN-CMP-001','tax_basis':'含税','contract_amount':'123.45','costs':[{'name':'合成材料','amount':'100.10'},{'name':'运费','amount':'0.20'}],'file_ids':[fid]})
        check('项目经理复核到货质量验收商务合同归档闭环',read('biz',proc+'/orders/'+ctx['purchase_id'])['state']=='archived')
    sid=ctx['spool_id']
    def taction(action,who,**kw):
        s=read(who,trace+'/workspace/spools/'+sid);return write(who,trace+'/spools/'+sid+'/actions',{'revision':s['revision'],'action':action,**kw})
    s=read('quality',trace+'/workspace/spools/'+sid)
    taction('inspect','quality',passed=True,reason='合成焊缝覆盖核对',file_ids=[ctx['trace_report_id']],weld_ids=[x['id'] for x in read('quality',trace+'/workspace/spools/'+sid+'/history?kind=welds&revision='+str(s['revision']))['items']])
    mode('after_inspection')
    taction('confirm_pressure','quality',passed=True,reason='合成试压核对',file_ids=[ctx['pressure_report_id']])
    taction('complete','quality',reason='合成材料焊缝预制发运安装试压均齐全')
    check('材料焊缝预制检测发运安装试压完成闭环',read('quality',trace+'/workspace/spools/'+sid)['state']=='completed')
    label=taction('label','factory');qr=ns['clients']['factory'].get('/api'+trace+'/spools/'+sid+'/qr');check('管段标签与二维码真实生成',bool(label['locator']) and qr.status_code==200)
    from PIL import Image
    buf=io.BytesIO();Image.new('RGB',(80,80),(20,110,90)).save(buf,'JPEG');raw=buf.getvalue()
    r=ns['clients']['quality'].post('/api'+trace+'/template-photos',files={'file':('camera.jpg',raw,'image/jpeg')},headers={'X-Idempotency-Key':'cmp-template-photo'});r.raise_for_status();photo=r.json()
    write('quality',trace+'/templates/'+ctx['template_id']+'/photos',{'photo_ids':[photo['id']]})
    r=ns['clients']['factory'].get('/api'+trace+'/template-photos/'+photo['id']);check('模板照片原件上传关联和跨岗位预览哈希一致',r.status_code==200 and r.content==raw)
    mode('change');c=read('pm',base+'/changes/'+ctx['change_id'])
    write('pm',base+'/changes/'+c['id']+'/actions',{'revision':c['revision'],'action':'publish','recipient_ids':c['required_recipient_ids']})
    mode('change_execute');c=read('pm',base+'/changes/'+ctx['change_id']);write('pm',base+'/changes/'+c['id']+'/actions',{'revision':c['revision'],'action':'close','version_id':c['current']['id']})
    check('变更四专业批准送达本人确认对象处置关闭完整闭环',read('pm',base+'/changes/'+ctx['change_id'])['state']=='closed')
    def batchwait(bid,state):
        for _ in range(200):
            b=read('finance',cost+'/batches/'+bid)
            if b['state']==state:return b
            time.sleep(.1)
        raise AssertionError(('batch timeout',state,b['state']))
    for name,bad in [('bad_csv',True),('good_csv',False)]:
        meta={'profile_id':ctx['profile_id'],'period':'2026-10','currency':'CNY','tax_basis':'含税','mode':'increment','reason':'合成版本比较财务导入','exported_at':datetime.now(timezone.utc).isoformat(),'data_cutoff':'2026-10-31T15:59:59+00:00'}
        r=ns['clients']['finance'].post('/api'+cost+'/batches',data={'meta':json.dumps(meta)},files={'file':(Path(ctx[name]).name,Path(ctx[name]).read_bytes(),'text/csv')},headers={'X-Idempotency-Key':'cmp-'+name});r.raise_for_status();bid=r.json()['id'];b=batchwait(bid,'mapping')
        write('finance',cost+'/batches/'+bid+'/actions',{'revision':b['revision'],'action':'mapping','mapping':ns['FIELDS']});b=batchwait(bid,'invalid' if bad else 'ready')
        if bad:check('错误财务源表4行整批拦截',len(b['errors'])==4)
        write('finance',cost+'/batches/'+bid+'/actions',{'revision':b['revision'],'action':'withdraw' if bad else 'commit','confirmed':True,'reason':'合成核对错误撤回' if bad else '合成核对来源金额后明确入账'})
if '--resume-close' not in sys.argv:mode('close_ready')
cl=next(x for x in read('finance',cost+'/workspace')['closes'] if x['id']==ctx['close_id']);write('finance',cost+'/closes/'+cl['id']+'/actions',{'revision':cl['revision'],'action':'publish','confirmed':True,'reason':'合成控制总额与日历核对后发布'})
check('合成财务月结快照发布完成',len(read('finance',cost+'/workspace')['snapshots'])==1)
task=write('pm',base+'/assurance/exports',{'confirmed':True,'include_sensitive':False,'reason':'双版本比较合成证据包'})
for _ in range(200):
    t=read('pm',base+'/assurance/exports/'+task['id'])
    if t['state']=='ready':break
    time.sleep(.1)
else:raise AssertionError('export timeout')
r=ns['clients']['pm'].get('/api'+base+'/assurance/exports/'+task['id']+'/download');r.raise_for_status();(OUT/'local-evidence-export.zip').write_bytes(r.content)
mode('verify');mode('revoke_observer');mode('restore_observer');mode('finance_revoke')
ns['publish_report']()
public={'project_id':pid,'spool_id':ctx['spool_id'],'purchase_id':ctx['purchase_id'],'change_id':ctx['change_id'],'close_id':ctx['close_id'],'template_id':ctx['template_id']}
(OUT/'local-flow-context.json').write_text(json.dumps(public,ensure_ascii=False,indent=2))
for c in ns['clients'].values():c.close()
print({'four_chains_complete':True,'checks_added':len(ns['CHECKS'])})
