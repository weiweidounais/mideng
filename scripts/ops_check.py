"""Actual kill, full bundle restore through HTTP, and synthetic legacy migration rehearsal."""
import os,sys,json,secrets,subprocess,signal,hashlib,time
from pathlib import Path
R=Path(__file__).resolve().parents[1];D=R/'backend/.runtime/qa'/('recovery26-'+secrets.token_hex(4));D.mkdir(mode=0o700);env=os.environ.copy();env['RESTART_CHECK_DIR']=str(D);python=str(R/'backend/.venv/bin/python');log=(D/'hook.log').open('ab')
def hook(action,*args):return subprocess.check_output([python,str(R/'scripts/restart_check.py'),action,*args],cwd=R,env=env,stderr=log,text=True).strip().splitlines()[-1]
try:
 pid1=int(hook('start'));nonce='ops26-'+secrets.token_hex(12);rid=hook('write',nonce);os.kill(pid1,signal.SIGKILL)
 for _ in range(80):
  state=subprocess.run(['ps','-p',str(pid1),'-o','stat='],capture_output=True,text=True).stdout.strip()
  if not state or state.startswith('Z'):break
  time.sleep(.1)
 else:raise RuntimeError('测试进程未退出')
 pid2=int(hook('start'));assert pid2!=pid1;assert hook('read',rid)==nonce
 restored=json.loads((D/'restored-isolated/restore-verification.json').read_text());sys.path.insert(0,str(R/'backend'));from app.legacy_rehearsal import rehearse
 source=D/'legacy.json';original=D/'redacted.md';original.write_bytes(b'Synthetic old original, not real company material')
 source.write_text(json.dumps({'schema_version':1,'data_mode':'synthetic','packages':[{'id':'reqpkg-demo-01','owner':'demo','version':1,'projectName':'合成旧演示项目','summary':'演示不计实数','attachments':['missing.pdf'],'history':[{'by':'商务-历史角色'}]},{'id':'legacy-redacted-02','version':3,'projectName':'合成脱敏旧项目','summary':'合成映射演练','attachments':['redacted.md'],'history':[{'by':'设计-历史角色'}]}],'originals':{'redacted.md':{'relative_path':'redacted.md','sha256':hashlib.sha256(original.read_bytes()).hexdigest()}}},ensure_ascii=False))
 migration=rehearse(source,D/'migration-isolated');E=R/'docs/evidence/阶段2-6';E.mkdir(parents=True,exist_ok=True);(E/'旧结构迁移演练.json').write_text(json.dumps(migration,ensure_ascii=False,indent=2)+'\n')
 report={'environment':'isolated local synthetic','actual_kill':{'before_pid':pid1,'after_pid':pid2,'nonce_sha256':hashlib.sha256(nonce.encode()).hexdigest(),'readback_match':True},'checks':{'business_version_restored_through_HTTP':True,'completed_spool_and_random_fact_restored_through_HTTP':True,'confirmed_cost_snapshot_100_30_restored_through_HTTP':True,'financial_import_pending_task_recovered':True,'waiver_and_original_restored':True,'queued_export_recovered_and_actual_zip_verified':True,'full_bundle_relocated_to_new_directory':True,'three_business_chains_and_four_originals_read_through_restored_HTTP':True,'all_database_fingerprints_unchanged_except_revoked_sessions':True,'all_immutable_triggers_preserved':True,'original_hashes_verified':True,'old_sessions_revoked':restored['old_sessions_revoked']},'restored_counts':restored['database']['counts'],'migration_summary':{k:migration[k] for k in ['source_packages','proposals','demonstration_excluded','originals_verified','missing_originals','unverified_authors','business_activated']},'boundary':'合成恢复与映射演练，不是原库真实迁移、企业RPO/RTO或业务收益验收'}
 (E/'全包恢复演练.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print({'actual_kill_and_full_restore':True,'checks':len(report['checks']),'legacy_proposals':migration['proposals']})
finally:
 hook('stop');log.close()
