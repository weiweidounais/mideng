"""Four-action hook; the parent verifier owns the kill and nonce comparison."""
import json
import hashlib
from contextlib import contextmanager
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
import secrets
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
DATA=Path(os.environ['RESTART_CHECK_DIR'])
STATE=DATA/'hook.json'


def start():
    if STATE.exists():
        state=json.loads(STATE.read_text())
        port=state['port']
    else:
        with socket.socket() as s:
            s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        state={'port':port,'password':secrets.token_urlsafe(16)}
        fd=os.open(STATE,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump(state,f)
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1',port))==0:
            raise RuntimeError('恢复检查端口已占用，未终止任何其他进程')
    env=os.environ.copy();env['PILOT_DATA_DIR']=str(DATA/'runtime');env['MODEL_API_KEY']=''
    with (DATA/'server.log').open('ab') as output:
        p=subprocess.Popen([str(ROOT/'backend/.venv/bin/python'),'-m','uvicorn','app.pilot:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=ROOT/'backend',env=env,stdin=subprocess.DEVNULL,stdout=output,stderr=output,start_new_session=True)
    state['pid']=p.pid;STATE.write_text(json.dumps(state));STATE.chmod(0o600)
    for _ in range(100):
        try:
            if httpx.get(f'http://127.0.0.1:{port}/api/health',timeout=1,trust_env=False).is_success:
                print(p.pid);return
        except httpx.HTTPError:pass
        if p.poll() is not None:raise RuntimeError('恢复服务提前退出，请查隔离日志')
        time.sleep(.1)
    p.terminate();raise RuntimeError('恢复服务启动超时')


@contextmanager
def client():
    state=json.loads(STATE.read_text())
    c=httpx.Client(base_url=f'http://127.0.0.1:{state["port"]}',trust_env=False,timeout=10)
    if c.get('/api/setup').json()['required']:
        r=c.post('/api/setup',json={'username':'restart-admin','display_name':'重启测试账号','password':state['password']})
    else:
        r=c.post('/api/auth/login',json={'username':'restart-admin','password':state['password']})
    r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];c.restart_account_id=r.json()['account']['id']
    try:
        yield c
    finally:
        c.close()


def main():
    action=sys.argv[1]
    if action=='start':start()
    elif action=='write':
        with client() as c:
            r=c.post('/api/projects',json={'code':'RESTART','name':sys.argv[2]},headers={'X-Idempotency-Key':'restart-check-request'})
            r.raise_for_status();project=r.json();pid=project['id']
            def write(method,path,body):
                response=c.request(method,path,json=body,headers={'X-Idempotency-Key':secrets.token_hex(16)})
                response.raise_for_status();return response.json()
            write('PUT','/api/projects/'+pid+'/members',{'account_id':c.restart_account_id,'roles':['管理员','商务','设计','采购','项目经理','质量','工厂','现场','财务'],'revision':1})
            base='/api/projects/'+pid+'/handoff'
            content=sys.argv[2].encode('utf-8')
            response=c.post(base+'/files',data={'kind':'requirement'},files={'file':('restart.md',content,'text/plain')},headers={'X-Idempotency-Key':secrets.token_hex(16)})
            response.raise_for_status();f=response.json()
            d=write('POST',base+'/documents',{'kind':'requirement','body':{'title':'恢复测试正式需求','summary':sys.argv[2],'source':'随机恢复检查','attachment_ids':[f['id']]}})
            d=write('POST',base+'/documents/'+d['id']+'/publish',{'revision':d['revision'],'recipient_ids':[c.restart_account_id],'diff_summary':'强杀前冻结'})
            scheme=write('POST',base+'/documents',{'kind':'scheme','parent_id':d['id'],'source_version_id':d['versions'][0]['id'],'body':{'title':'恢复关联方案','notes':'检查正式来源和料表','bom':[{'material':'测试管材','spec':'DN100','quantity':'0.3','unit':'米','need_by':'2026-12-01'}]}})
            scheme=write('POST',base+'/documents/'+scheme['id']+'/publish',{'revision':scheme['revision'],'recipient_ids':[c.restart_account_id],'diff_summary':'冻结BOM'})
            contract=write('POST',base+'/contracts',{'version_id':scheme['versions'][0]['id'],'recipient_id':c.restart_account_id,'deliverable':'恢复测试交接','quality_rule':'来源、物料、数量、单位一致'})
            for _ in range(30):
                todos=c.get('/api/todos');todos.raise_for_status()
                if any(t.get('version_id')==d['versions'][0]['id'] for t in todos.json()):break
                time.sleep(.1)
            else:raise AssertionError('正式版本待办未持久化')
            proc='/api/projects/'+pid+'/procurement'
            order=write('POST',proc+'/orders',{'version_id':scheme['versions'][0]['id'],'title':'恢复采购闭环','note':'随机标记真实业务恢复','purchase_id':c.restart_account_id,'quality_id':c.restart_account_id,'commerce_id':c.restart_account_id})
            def action(name,**extra):
                nonlocal_order=write('POST',proc+'/orders/'+order['id']+'/actions',{'revision':order['revision'],'action':name,**extra})
                order.update(nonlocal_order)
            action('accept_purchase')
            action('submit_result',result={'supplier':'恢复合成供应商','lines':[{'line_no':1,'quantity':'0.3','eta':'2026-12-01'}]})
            action('approve_purchase')
            action('arrival',arrival={'line_no':1,'quantity':'0.3','occurred_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()})
            def upload(purpose):
                response=c.post(proc+'/orders/'+order['id']+'/files',data={'purpose':purpose},files={'file':('recovery.md',content,'text/plain')},headers={'X-Idempotency-Key':secrets.token_hex(16)})
                response.raise_for_status();return response.json()['id']
            quality_file=upload('quality');action('pass_quality',file_ids=[quality_file])
            archive_file=upload('archive');action('archive',archive={'contract_no':'RESTART-TEST','tax_basis':'含税','contract_amount':'1.00','costs':[{'name':'合成成本','amount':'0.30'}],'file_ids':[archive_file]})
            tracebase='/api/projects/'+pid+'/trace'
            import io
            from PIL import Image,PngImagePlugin
            photo_stream=io.BytesIO();photo_info=PngImagePlugin.PngInfo();photo_info.add_text('recovery',sys.argv[2]);Image.new('RGB',(80,50),(30,120,100)).save(photo_stream,format='PNG',pnginfo=photo_info);photo_bytes=photo_stream.getvalue()
            response=c.post(tracebase+'/template-photos',files={'file':('recovery-photo.png',photo_bytes,'image/png')},headers={'X-Idempotency-Key':secrets.token_hex(16)});response.raise_for_status();photo_id=response.json()['id'];photo_hash=hashlib.sha256(photo_bytes).hexdigest()
            template=write('POST',tracebase+'/templates',{'name':'恢复合成模板','scope':'仅恢复验证','welding':True,'pressure':True,'basis':'合成质量岗位明确确认适用工序','photo_ids':[photo_id]})
            work=write('POST',tracebase+'/orders',{'code':'RESTART-FAB','version_id':scheme['versions'][0]['id'],'factory_id':c.restart_account_id,'site_id':c.restart_account_id,'quality_id':c.restart_account_id})
            spool=write('POST',tracebase+'/spools',{'code':'RESTART-SPOOL','order_id':work['id'],'template_id':template['id']})
            def sv():
                response=c.get(tracebase+'/board');response.raise_for_status();return next(x for x in response.json()['spools'] if x['id']==spool['id'])
            def sa(action,**extra):return write('POST',tracebase+'/spools/'+spool['id']+'/actions',{'revision':sv()['revision'],'action':action,**extra})
            def sr(kind,data,**extra):return write('POST',tracebase+'/spools/'+spool['id']+'/records',{'revision':sv()['revision'],'kind':kind,'data':data,'occurred_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),**extra})
            trace_files=[]
            def sf():
                response=c.post(tracebase+'/spools/'+spool['id']+'/files',files={'file':('trace-recovery.md',content,'text/plain')},headers={'X-Idempotency-Key':secrets.token_hex(16)});response.raise_for_status();fid=response.json()['id'];trace_files.append(fid);return fid
            sr('material',{'batch':sys.argv[2]},file_ids=[sf()]);sa('start')
            sr('weld',{'weld_code':'RESTART-WELD','welder_code':'SYN-QUAL','consumable_batch':'SYN-WIRE','equipment':'SYN-EQ'})
            sr('fabrication',{'equipment':'SYN-EQ','description':'合成预制记录'});sa('submit_inspection')
            sa('inspect',passed=True,reason='合成质量核对',file_ids=[sf()],weld_ids=[w['id'] for w in sv()['welds']])
            for action in ['ship','install']:sa(action,location='合成位置',reference='SYN-LOCATION',occurred_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat())
            sr('pressure',{'equipment':'SYN-PRESSURE','description':'合成试压'},file_ids=[sf()]);sa('confirm_pressure',passed=True,reason='合成报告核对',file_ids=[sf()]);sa('complete',reason='合成履历齐全');sa('label');sa('label')
            original_version=d['versions'][0]
            d=write('POST',base+'/documents/'+d['id']+'/revise',{'revision':d['revision']})
            d=write('PATCH',base+'/documents/'+d['id'],{'revision':d['revision'],'body':original_version['body']|{'summary':sys.argv[2]+' revised'}})
            d=write('POST',base+'/documents/'+d['id']+'/publish',{'revision':d['revision'],'recipient_ids':[c.restart_account_id],'diff_summary':'恢复变更来源'})
            changebase='/api/projects/'+pid+'/changes'
            change=write('POST',changebase,{'title':sys.argv[2],'reason':'合成恢复变更','old_version_id':original_version['id'],'new_version_id':d['versions'][0]['id']})
            def cv():
                response=c.get(changebase+'/board');response.raise_for_status();return next(x for x in response.json()['cases'] if x['id']==change['id'])
            def ca(action,**extra):
                current=cv();result=write('POST',changebase+'/'+change['id']+'/actions',{'revision':current['revision'],'version_id':current['current']['id'] if current['current'] else None,'action':action,**extra});change.update(result)
            def cf(purpose):
                response=c.post(changebase+'/'+change['id']+'/files',data={'purpose':purpose},files={'file':('change-recovery.md',content,'text/plain')},headers={'X-Idempotency-Key':secrets.token_hex(16)});response.raise_for_status();return response.json()['id']
            for category in ['technical','cost','schedule','quality']:ca('impact',category=category,has_impact=False,reason='合成专业无影响核对')
            approval_file=cf('approval');ca('approval',approval_no='SYNTHETIC-RESTART',reason='登记合成既有批准',file_ids=[approval_file]);ca('publish',recipient_ids=cv()['required_recipient_ids'])
            for _ in range(50):
                if all(r['delivered_at'] for r in cv()['current']['receipts']):break
                time.sleep(.1)
            else:raise AssertionError('变更待办未实际送达')
            ca('ack');change_files=[]
            for target in cv()['current']['body']['targets']:
                ca('plan',target_key=target['key'],decision='continue',reason='合成批准继续使用')
                evidence=cf('execution');change_files.append(evidence)
                ca('execute',target_key=target['key'],reason='实际核对完成',file_ids=[evidence]);ca('verify',target_key=target['key'])
            ca('request_close');ca('close')
            # Financial source, confirmed snapshot and queued parsing survive an actual kill.
            from datetime import datetime,timezone
            sys.path.insert(0,str(ROOT/"backend"))
            from app.cost_import import FIELDS
            import csv,io
            cb='/api/projects/'+pid+'/cost'
            profile=write('POST',cb+'/profiles',{'source_system':'RESTART','name':'恢复已确认映射','subjects':{'6601':'成本'},'wbs':{'W1':'工程'},'key_mode':'id','estimate_policy':'separate','basis':'合成恢复检查确认映射'})
            response=c.post(cb+'/evidence',files={'file':('cost-recovery.md',content,'text/plain')},headers={'X-Idempotency-Key':secrets.token_hex(16)});response.raise_for_status();cost_evidence=response.json()['id']
            write('POST',cb+'/budgets',{'currency':'CNY','tax_basis':'含税','kind':'baseline','amount':'150.00','approval_no':'SYN-RESTART','basis':'合成批准基线','file_ids':[cost_evidence]})
            cal=write('POST',cb+'/calendars',{'name':'恢复合成工作日历','start':'2026-11-01','end':'2026-11-15','workdays':['2026-11-03','2026-11-04','2026-11-05'],'basis':'合成明确工作日'})
            now=datetime.now(timezone.utc).isoformat()
            meta={'profile_id':profile['id'],'period':'2026-10','currency':'CNY','tax_basis':'含税','mode':'increment','reason':'合成恢复源','exported_at':now,'data_cutoff':'2026-10-31T15:59:59+00:00'}
            def cost_upload(key,amount):
                stream=io.StringIO();writer=csv.writer(stream);writer.writerow(FIELDS.values());row={'source_id':key,'line_version':'1','project_code':'RESTART','entry_date':'2026-10-15','subject_code':'6601','wbs_code':'W1','kind':'实际','business_id':key,'amount':amount,'quantity':'1','unit':'笔','currency':'CNY','tax_basis':'含税','note':sys.argv[2]};writer.writerow([row.get(k,'') for k in FIELDS]);raw=stream.getvalue().encode()
                response=c.post(cb+'/batches',data={'meta':json.dumps(meta)},files={'file':('restart.csv',raw,'text/csv')},headers={'X-Idempotency-Key':secrets.token_hex(16)});response.raise_for_status();return response.json(),hashlib.sha256(raw).hexdigest()
            def cost_batch(bid,state):
                for _ in range(200):
                    response=c.get(cb+'/batches/'+bid);response.raise_for_status();v=response.json()
                    if v['state']==state:return v
                    if v['state']=='invalid':raise AssertionError('恢复合成成本预检失败')
                    time.sleep(.1)
                raise AssertionError('恢复成本后台任务超时')
            cost_batch_id,cost_hash=cost_upload('RESTART-A','100.30');v=cost_batch(cost_batch_id['id'],'mapping');write('POST',cb+'/batches/'+v['id']+'/actions',{'revision':v['revision'],'action':'mapping','mapping':FIELDS});v=cost_batch(v['id'],'ready');cost_source=v['source_id'];write('POST',cb+'/batches/'+v['id']+'/actions',{'revision':v['revision'],'action':'commit','confirmed':True,'reason':'合成财务确认'})
            close=write('POST',cb+'/closes',{'period':'2026-10','currency':'CNY','tax_basis':'含税','calendar_id':cal['id'],'control_total':'100.30','control_basis':'合成会计控制合计','reason':sys.argv[2]})
            for act in ['submit_review','publish']:
                response=c.get(cb+'/board');response.raise_for_status();v=next(x for x in response.json()['closes'] if x['id']==close['id']);write('POST',cb+'/closes/'+v['id']+'/actions',{'revision':v['revision'],'action':act,'confirmed':True,'reason':'合成财务恢复确认'})
            response=c.get(cb+'/board');response.raise_for_status();cost_snapshot=response.json()['snapshots'][0]['id']
            cost_pending,_=cost_upload('RESTART-PENDING','0.01')
            assurance='/api/projects/'+pid+'/assurance'
            exceptional=write('POST',base+'/documents',{'kind':'requirement','body':{'title':'恢复异常待交底','summary':sys.argv[2],'source':'合成恢复核对','attachment_ids':[],'brief_due_at':'2000-01-01T00:00:00+00:00'}})
            response=c.get(assurance+'/board');response.raise_for_status();exception=next(x for x in response.json()['exceptions'] if x['object_id']==exceptional['id'])
            response=c.post(assurance+'/exceptions/'+exception['id']+'/files',files={'file':('assurance-recovery.md',content,'text/plain')},headers={'X-Idempotency-Key':secrets.token_hex(16)});response.raise_for_status();exception_file=response.json()['id']
            write('POST',assurance+'/exceptions/'+exception['id']+'/actions',{'revision':exception['revision'],'action':'waive','reason':sys.argv[2],'approval_no':'SYN-RESTART','until':(datetime.now(timezone.utc)+__import__('datetime').timedelta(days=1)).isoformat(),'file_ids':[exception_file]})
            evidence_export=write('POST',assurance+'/exports',{'confirmed':True,'include_sensitive':True,'reason':'合成重启恢复授权导出'})
            print(':'.join([pid,d['id'],f['id'],scheme['id'],contract['id'],order['id'],quality_file,archive_file,change['id'],approval_file,','.join(change_files),spool['id'],','.join(trace_files),photo_id,photo_hash,cost_batch_id['id'],cost_source,cost_hash,cost_evidence,cost_snapshot,cost_pending['id'],exception['id'],exception_file,evidence_export['id']]))
    elif action=='read':
        with client() as c:
            pid,did,handoff_fid,sid,cid,order_id,quality_id,archive_id,change_id,approval_file,change_files,spool_id,trace_files,photo_id,photo_hash,cost_bid,cost_source,cost_hash,cost_evidence,cost_snapshot,cost_pending,exception_id,exception_file,export_id=sys.argv[2].split(':')
            base='/api/projects/'+pid+'/handoff'
            r=c.get('/api/projects/'+pid);r.raise_for_status();project=r.json()
            r=c.get(base+'/board');r.raise_for_status();board=r.json()
            document=next(d for d in board['documents'] if d['id']==did)
            scheme=next(d for d in board['documents'] if d['id']==sid)
            contract=next(c for c in board['contracts'] if c['id']==cid)
            version=next(v for v in document['versions'] if v['id']==scheme['versions'][0]['source_version_id']);f=next(f for f in version['attachments'] if f['id']==handoff_fid)
            original=c.get(base+'/files/'+handoff_fid);original.raise_for_status()
            assert project['name']==version['body']['summary']==original.content.decode('utf-8')
            assert hashlib.sha256(original.content).hexdigest()==f['sha256']
            assert scheme['versions'][0]['source_version_id']==version['id']
            assert contract['version_id']==scheme['versions'][0]['id']
            assert next(row for row in board['rows'] if row['contract_id']==cid)['quantity']=='0.3'
            assert board['events'] and document['has_draft'] is False
            r=c.get('/api/todos');r.raise_for_status()
            assert any(t.get('version_id')==version['id'] for t in r.json())
            proc='/api/projects/'+pid+'/procurement'
            response=c.get(proc+'/board');response.raise_for_status()
            recovered=next(o for o in response.json()['orders'] if o['id']==order_id)
            assert recovered['state']=='archived' and recovered['version_id']==scheme['versions'][0]['id']
            workspace='/api/projects/'+pid+'/workspace'
            response=c.get(workspace+'/locate',params={'section':'procurement','object_id':order_id,'version_id':recovered['version_id'],'kind':'procurement'});response.raise_for_status();assert response.json()['object_id']==order_id
            response=c.get(workspace+'/purchase-orders/'+order_id);response.raise_for_status();assert response.json()['order']['state']=='archived' and response.json()['comparison'][0]['required_quantity']=='0.3'
            response=c.get('/api/workbench?mode=all');response.raise_for_status();assert any(t['link']['object_id']==order_id and not t['pending'] for t in response.json()['items'])
            assert recovered['archive']['contract_amount']=='1.00' and recovered['archive_total']=='0.30'
            assert recovered['arrivals'][0]['quantity']=='0.3' and len(recovered['events'])==7
            for file_id in [quality_id,archive_id]:
                response=c.get(proc+'/files/'+file_id);response.raise_for_status()
                assert response.content.decode('utf-8')==version['body']['summary']
            changebase='/api/projects/'+pid+'/changes'
            response=c.get(changebase+'/board');response.raise_for_status();change=next(x for x in response.json()['cases'] if x['id']==change_id)
            assert change['state']=='closed' and change['current']['body']['title']==version['body']['summary']
            assert all(r['delivered_at'] and r['confirmed_at'] for r in change['current']['receipts'])
            assert all(d['verified_at'] and d['submitted_at'] for d in change['current']['dispositions'])
            for file_id in [approval_file,*change_files.split(',')]:
                response=c.get(changebase+'/files/'+file_id);response.raise_for_status();assert response.content==original.content
            tracebase='/api/projects/'+pid+'/trace'
            response=c.get(tracebase+'/board');response.raise_for_status();trace=response.json();spool=next(x for x in trace['spools'] if x['id']==spool_id)
            assert spool['state']=='completed' and spool['source_ok'] and not spool['missing']
            assert trace['metrics']['completed_total']==trace['metrics']['completed_valid']==1
            assert any(r['kind']=='weld' and r['data']['welder_code']=='SYN-QUAL' for r in spool['records'])
            assert len([e for e in spool['events'] if e['action']=='label'])==2
            for fid in trace_files.split(','):
                response=c.get(tracebase+'/files/'+fid);response.raise_for_status();assert response.content==original.content
            template=next(t for t in trace['templates'] if t['id']==spool['template_id']);assert any(p['id']==photo_id and p['sha256']==photo_hash for p in template['photos'])
            response=c.get(tracebase+'/template-photos/'+photo_id);response.raise_for_status();assert hashlib.sha256(response.content).hexdigest()==photo_hash
            import io
            from PIL import Image
            with Image.open(io.BytesIO(response.content)) as photo:assert photo.info['recovery']==version['body']['summary']
            cb='/api/projects/'+pid+'/cost'
            response=c.get(cb+'/board');response.raise_for_status();cost=response.json();snap=next(x for x in cost['snapshots'] if x['id']==cost_snapshot)
            assert snap['body']['actual_accounting']=='100.30' and snap['body']['current_budget']=='150.00'
            assert next(x for x in cost['batches'] if x['id']==cost_bid)['state']=='committed'
            saved_cost_batch=next(x for x in cost['batches'] if x['id']==cost_bid)
            response=c.get(cb+'/workspace',params={'kind':'cost_batch','object_id':cost_bid});response.raise_for_status();bounded=response.json()['batches'][0]
            assert bounded['rows']==bounded['normalized']==[] and bounded['rows_count']==len(saved_cost_batch['rows'])
            response=c.get(cb+'/batches/'+cost_bid+'/review-rows',params={'kind':'normalized','revision':bounded['revision'],'page_size':2});response.raise_for_status()
            assert response.json()['total']==len(saved_cost_batch['normalized']) and len(response.json()['items'])==min(2,len(saved_cost_batch['normalized']))
            response=c.get(cb+'/files/'+cost_source);response.raise_for_status();assert hashlib.sha256(response.content).hexdigest()==cost_hash and original.content in response.content
            response=c.get(cb+'/files/'+cost_evidence);response.raise_for_status();assert response.content==original.content
            for _ in range(200):
                response=c.get(cb+'/batches/'+cost_pending);response.raise_for_status();v=response.json()
                if v['state']=='mapping':break
                time.sleep(.1)
            else:raise AssertionError('重启后解析任务未恢复')
            assert any(original.content.decode() in str(row) for row in v['rows'])
            assurance='/api/projects/'+pid+'/assurance'
            response=c.get(assurance+'/board');response.raise_for_status();ex=next(x for x in response.json()['exceptions'] if x['id']==exception_id)
            assert ex['state']=='waived' and ex['waiver']['reason']==version['body']['summary']
            response=c.get(assurance+'/files/'+exception_file);response.raise_for_status();assert response.content==original.content
            for _ in range(300):
                response=c.get(assurance+'/exports/'+export_id);response.raise_for_status();task=response.json()
                if task['state']=='ready':break
                assert task['state']!='failed',task['error'];time.sleep(.1)
            else:raise AssertionError('重启后证据导出未恢复')
            response=c.get(assurance+'/exports/'+export_id+'/download');response.raise_for_status()
            import zipfile
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                manifest=json.loads(z.read('manifest.json'));assert version['body']['summary'] in z.read('objects.json').decode()
                for f in manifest['files']:assert hashlib.sha256(z.read(f['path'])).hexdigest()==f['sha256']
            # A second, relocated data directory must serve the same business facts through HTTP.
            from app.data_bundle import backup,restore
            archive=DATA/'full-backup.zip';restore_dir=DATA/'restored-isolated';backup(DATA/'runtime',archive);restore(archive,restore_dir)
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));restored_port=sock.getsockname()[1]
            restored_env=os.environ.copy();restored_env['PILOT_DATA_DIR']=str(restore_dir);restored_env['MODEL_API_KEY']=''
            with (DATA/'restored-server.log').open('ab') as log:
                process=subprocess.Popen([str(ROOT/'backend/.venv/bin/python'),'-m','uvicorn','app.pilot:app','--host','127.0.0.1','--port',str(restored_port),'--no-access-log'],cwd=ROOT/'backend',env=restored_env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
            try:
                for _ in range(100):
                    try:
                        if httpx.get(f'http://127.0.0.1:{restored_port}/api/health',timeout=1,trust_env=False).is_success:break
                    except httpx.HTTPError:pass
                    if process.poll() is not None:raise AssertionError('隔离恢复服务未启动')
                    time.sleep(.1)
                with httpx.Client(base_url=f'http://127.0.0.1:{restored_port}',trust_env=False,timeout=20) as restored:
                    state=json.loads(STATE.read_text());rr=restored.post('/api/auth/login',json={'username':'restart-admin','password':state['password']});rr.raise_for_status()
                    rb=restored.get(base+'/board');rb.raise_for_status();assert any(v['body'].get('summary')==version['body']['summary'] for d in rb.json()['documents'] for v in d['versions'])
                    rb=restored.get(tracebase+'/board');rb.raise_for_status();rs=next(x for x in rb.json()['spools'] if x['id']==spool_id);assert rs['state']=='completed' and any(r['data'].get('batch')==version['body']['summary'] for r in rs['records'])
                    rb=restored.get(cb+'/board');rb.raise_for_status();assert next(x for x in rb.json()['snapshots'] if x['id']==cost_snapshot)['body']['actual_accounting']=='100.30'
                    for path in [base+'/files/'+handoff_fid,tracebase+'/files/'+trace_files.split(',')[0],cb+'/files/'+cost_evidence,assurance+'/files/'+exception_file]:
                        rr=restored.get(path);rr.raise_for_status();assert rr.content==original.content
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            print(next(r['data']['batch'] for r in spool['records'] if r['kind']=='material'))
    elif action=='stop':
        if STATE.exists():
            state=json.loads(STATE.read_text());pid=state.get('pid')
            if pid:
                # A previous failed write may have left the owned first process alive.
                command=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True).stdout
                expected=str(ROOT/'backend/.venv/bin/python')
                if command.startswith(expected) and 'app.pilot:app' in command and ('--port '+str(state['port'])) in command:
                    try:os.kill(pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                    for _ in range(50):
                        try:os.kill(pid,0)
                        except ProcessLookupError:break
                        time.sleep(.1)
        print('恢复检查结束')
    else:raise ValueError('未知检查动作')


if __name__=='__main__':main()
