"""Local maintenance bundle. Not exposed as a web endpoint or a project export."""
import hashlib,json,os,shutil,sqlite3,tempfile,zipfile,uuid
from pathlib import Path,PurePosixPath
HEAD='pilot_011'
DIRECTORIES={'attachments','procurement-originals','change-originals','trace-originals','template-photos','cost-originals','assurance-originals','evidence-exports','knowledge-originals'}
PATH_TABLES={'procurement_files','change_files','trace_files','trace_template_photos','cost_sources','assurance_files','assurance_exports','knowledge_documents'}

def digest(raw):return hashlib.sha256(raw).hexdigest()
def tables(db):return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
def inspect(db):
 if db.execute('pragma integrity_check').fetchone()[0]!='ok' or db.execute('pragma foreign_key_check').fetchall():raise ValueError('数据库完整性或外键检查失败')
 if db.execute('select version_num from alembic_version').fetchone()[0]!=HEAD:raise ValueError('备份模式版本与当前入口不一致，先在原环境完成受控升级')
 counts={};fingerprints={}
 for t in tables(db):
  columns=[x[1] for x in db.execute('pragma table_info("'+t+'")')];rows=[]
  for raw in db.execute('select * from "'+t+'"'):
   row=list(raw)
   if 'path' in columns and row[columns.index('path')]:
    p=Path(row[columns.index('path')]);row[columns.index('path')]=p.parent.name+'/'+p.name
   rows.append(row)
  counts[t]=len(rows)
  if t!='pilot_sessions':fingerprints[t]=digest(json.dumps(sorted(rows,key=lambda x:json.dumps(x,sort_keys=True)),ensure_ascii=False,sort_keys=True).encode())
 triggers={r[0]:digest(r[1].encode()) for r in db.execute("select name,sql from sqlite_master where type='trigger' order by name")}
 return {'counts':counts,'fingerprints':fingerprints,'triggers':triggers}

def references(db,root):
 result=[]
 if 'handoff_files' in tables(db):result += [('attachments/'+r[0],r[1]) for r in db.execute('select id,sha256 from handoff_files')]
 for table in PATH_TABLES & set(tables(db)):
  for path,sha in db.execute('select path,sha256 from "'+table+'" where path is not null'):
   p=Path(path)
   try:rel=p.resolve().relative_to(root.resolve()).as_posix()
   except ValueError:raise ValueError('原件路径不属于本运行目录')
   if len(PurePosixPath(rel).parts)!=2 or PurePosixPath(rel).parts[0] not in DIRECTORIES:raise ValueError('未知原件目录')
   result.append((rel,sha))
 return result

def backup(source,output):
 source=Path(source).resolve();output=Path(output).resolve()
 if output.exists():raise ValueError('输出已存在，禁止覆盖')
 if source.is_symlink() or not (source/'pilot.db').is_file():raise ValueError('请选择本机运行数据目录')
 output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 with tempfile.TemporaryDirectory(prefix='mideng-backup-',dir=output.parent) as tmp:
  temp=Path(tmp);db=sqlite3.connect('file:'+str(source/'pilot.db')+'?mode=ro',uri=True);copy=sqlite3.connect(temp/'pilot.db')
  try:db.backup(copy)
  finally:db.close();copy.close()
  copy=sqlite3.connect(temp/'pilot.db');summary=inspect(copy);refs=references(copy,source);copy.close()
  for d in DIRECTORIES:
   directory=source/d
   if directory.exists():
    if directory.is_symlink() or any(p.is_symlink() for p in directory.rglob('*')):raise ValueError('备份拒绝符号链接')
    shutil.copytree(directory,temp/d)
  for rel,sha in refs:
   p=temp/rel
   if not p.is_file() or digest(p.read_bytes())!=sha:raise ValueError('备份引用的原件缺失或哈希不符')
  files=[]
  for p in sorted(temp.rglob('*')):
   if p.is_file():files.append({'path':p.relative_to(temp).as_posix(),'sha256':digest(p.read_bytes()),'size':p.stat().st_size})
  manifest={'kind':'mideng-local-backup','schema_version':1,'migration':HEAD,'model_enabled':False,'indexes':'SQLite schema indexes included; no vector index mounted','external_secrets':'none required by disabled-model pilot; login hashes in database, old sessions revoked on restore','files':files,'database':summary}
  with output.open('xb') as stream:
   os.chmod(output,0o600)
   with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
    for f in files:z.write(temp/f['path'],f['path'])
    z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
 return manifest

def restore(archive,target):
 archive=Path(archive);target=Path(target).resolve()
 if target.exists():raise ValueError('恢复仅允许新的隔离目录，禁止覆盖现有数据')
 with zipfile.ZipFile(archive) as z:
  infos=z.infolist();names=[x.filename for x in infos]
  if len(names)!=len(set(names)) or len(names)>100000 or sum(x.file_size for x in infos)>1024*1024*1024:raise ValueError('备份数量或解压尺寸异常')
  for i in infos:
   parts=PurePosixPath(i.filename).parts
   if not parts or i.filename.startswith('/') or '\\' in i.filename or any(p in {'.','..'} for p in parts) or (i.external_attr>>16)&0o170000==0o120000 or i.flag_bits&1:raise ValueError('备份路径/链接或加密格式无效')
  manifest=json.loads(z.read('manifest.json'))
  if manifest.get('kind')!='mideng-local-backup' or manifest.get('schema_version')!=1 or manifest.get('migration')!=HEAD or manifest.get('model_enabled') is not False:raise ValueError('不是当前本机入口的可恢复备份')
  files=manifest['files'];expected={x['path'] for x in files}
  if set(names)!=expected|{'manifest.json'} or len(expected)!=len(files):raise ValueError('备份清单与文件不一致')
  for f in files:
   parts=PurePosixPath(f['path']).parts
   if f['path']!='pilot.db' and (len(parts)!=2 or parts[0] not in DIRECTORIES):raise ValueError('备份存在未知文件')
   raw=z.read(f['path'])
   if len(raw)!=f['size'] or digest(raw)!=f['sha256']:raise ValueError('备份文件哈希不一致')
  target.mkdir(mode=0o700,parents=True)
  try:
   for f in files:
    p=target/f['path'];p.parent.mkdir(mode=0o700,exist_ok=True);p.write_bytes(z.read(f['path']));p.chmod(0o600)
   db=sqlite3.connect(target/'pilot.db')
   try:
    before=inspect(db)
    if before!=manifest['database']:raise ValueError('数据库清单不一致')
    # Relocation is a maintenance-only transaction; restore every original trigger before commit.
    db.execute('BEGIN EXCLUSIVE')
    triggers=list(db.execute("select name,sql from sqlite_master where type='trigger'"))
    for name,_ in triggers:db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')
    for t in PATH_TABLES & set(tables(db)):
     for rid,path in list(db.execute('select id,path from "'+t+'" where path is not null')):
      old=Path(path);rel=old.parent.name+'/'+old.name
      if rel not in expected:raise ValueError('恢复原件引用未被清单覆盖')
      db.execute('update "'+t+'" set path=? where id=?',(str(target/rel),rid))
    db.execute('delete from pilot_sessions')
    for _,sql in triggers:db.execute(sql)
    db.commit();after=inspect(db)
    if after['fingerprints']!=before['fingerprints'] or after['triggers']!=before['triggers']:raise ValueError('恢复后的事实或不可变约束发生变化')
    for rel,sha in references(db,target):
     if digest((target/rel).read_bytes())!=sha:raise ValueError('恢复原件校验不一致')
   finally:db.close()
   (target/'restore-verification.json').write_text(json.dumps({'migration':HEAD,'verified':True,'old_sessions_revoked':True,'database':after},ensure_ascii=False));(target/'restore-verification.json').chmod(0o600)
  except BaseException:
   shutil.rmtree(target);raise
 return after
