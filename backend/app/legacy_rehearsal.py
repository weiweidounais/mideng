"""Old collaboration package mapping rehearsal. Staging facts never become operational data."""
import hashlib,json,sqlite3,uuid
from pathlib import Path

def rehearse(source,target):
 source=Path(source).resolve();target=Path(target).resolve()
 if target.exists():raise ValueError('迁移演练只允许新隔离目录')
 raw=source.read_bytes()
 if len(raw)>20*1024*1024:raise ValueError('演练输入超过20MB')
 data=json.loads(raw)
 if data.get('schema_version')!=1 or data.get('data_mode') not in {'synthetic','redacted'}:raise ValueError('输入须明确标为合成或脱敏，不接受未分类真实数据')
 packages=data.get('packages')
 if not isinstance(packages,list) or len(packages)>5000:raise ValueError('旧需求包须为最多5000条列表')
 ids=set();proposals=[];originals={};demo_count=0
 for item in packages:
  if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not item['id'] or item['id'] in ids or not isinstance(item.get('version'),int) or item['version']<1:raise ValueError('旧ID/版本须有效且唯一')
  ids.add(item['id']);demo=bool(item.get('demo') or item.get('owner')=='demo' or 'demo' in item['id'].lower());demo_count+=demo
  names=item.get('attachments',[])
  if not isinstance(names,list) or any(not isinstance(x,str) for x in names):raise ValueError('旧附件名称无效')
  blockers=['历史角色作者未实名核验','待业务确认项目/来源与初始正式版本']
  attachments=[]
  for name in names:
   meta=data.get('originals',{}).get(name)
   if not meta:attachments.append({'legacy_name':name,'status':'original_missing'});blockers.append('缺原件：'+name);continue
   path=(source.parent/meta['relative_path']).resolve()
   if source.parent not in path.parents or path.is_symlink() or not path.is_file():raise ValueError('演练原件路径不属于输入资料目录')
   content=path.read_bytes();sha=hashlib.sha256(content).hexdigest()
   if sha!=meta['sha256']:raise ValueError('演练原件哈希不一致')
   fid=uuid.uuid4().hex;originals[fid]=content;attachments.append({'legacy_name':name,'status':'verified_redacted_original','id':fid,'sha256':sha})
  legacy_authors=[h.get('by','') for h in item.get('history',[]) if isinstance(h,dict)]
  proposals.append({'legacy_id':item['id'],'legacy_version':item['version'],'proposal_id':uuid.uuid4().hex,'classification':'demonstration' if demo else data['data_mode'],'excluded_from_business_metrics':True,'legacy_authors':legacy_authors,'actor_id':None,'identity_status':'unverified_historical_role','project_name_original':item.get('projectName'),'target_kind':'requirement','initial_version_number':1,'source_version_number_preserved':item['version'],'body':{'title':item.get('projectName','历史需求'),'summary':item.get('summary',''),'constraints':item.get('constraints',''),'source':'旧结构演练，原始快照只读留存'},'attachments':attachments,'blockers':blockers,'operationally_activated':False})
 target.mkdir(parents=True,mode=0o700)
 try:
  (target/'source.json').write_bytes(raw);(target/'source.json').chmod(0o600);(target/'originals').mkdir(mode=0o700)
  for fid,content in originals.items():p=target/'originals'/fid;p.write_bytes(content);p.chmod(0o600)
  db=sqlite3.connect(target/'staging.db');db.executescript('CREATE TABLE legacy_snapshots(id TEXT PRIMARY KEY,body TEXT NOT NULL,sha256 TEXT NOT NULL); CREATE TABLE target_proposals(legacy_id TEXT PRIMARY KEY,proposal_id TEXT UNIQUE,body TEXT NOT NULL);')
  for item,proposal in zip(packages,proposals):
   text=json.dumps(item,ensure_ascii=False,sort_keys=True);db.execute('INSERT INTO legacy_snapshots VALUES(?,?,?)',(item['id'],text,hashlib.sha256(text.encode()).hexdigest()));db.execute('INSERT INTO target_proposals VALUES(?,?,?)',(item['id'],proposal['proposal_id'],json.dumps(proposal,ensure_ascii=False)))
  for table in ['legacy_snapshots','target_proposals']:
   for action in ['UPDATE','DELETE']:db.execute(f"CREATE TRIGGER {table}_no_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable rehearsal fact'); END")
  db.commit();assert db.execute('select count(*) from legacy_snapshots').fetchone()[0]==len(packages);db.close();(target/'staging.db').chmod(0o600)
  report={'schema_version':1,'source_sha256':hashlib.sha256(raw).hexdigest(),'source_packages':len(packages),'proposals':len(proposals),'demonstration_excluded':demo_count,'originals_verified':len(originals),'missing_originals':sum(x['status']=='original_missing' for p in proposals for x in p['attachments']),'unverified_authors':len(proposals),'business_activated':0,'mappings':proposals,'boundary':'仅隔离映射演练；未冒充实名、未补造原件、未激活业务或切换维护源'}
  (target/'migration-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));(target/'migration-report.json').chmod(0o600)
 except BaseException:
  import shutil
  shutil.rmtree(target);raise
 return report
