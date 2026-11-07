from .pilot_service import business_roles
"""Same authorization projections as business reads, plus bounded immutable originals."""
import csv,io,json,hashlib,zipfile
from pathlib import Path
from datetime import datetime,timedelta,timezone
from sqlalchemy import select
from .pilot_models import Account,utcnow
from .pilot_service import fail,uid
from . import handoff_service as hs,change_service as cs,trace_service as ts,procurement_service as ps,cost_service as fs
from .handoff_models import Document,Contract,MaterialRow,Arrival,Attachment
from .procurement_models import PurchaseOrder,PurchaseFile
from .change_models import ChangeCase,ChangeFile
from .trace_models import Spool,TraceTemplate,TraceOrder,TraceFile,TemplatePhoto
from .template_photos import template_view
from .assurance_models import EvidenceExport,ExceptionCase,ExceptionFile
from . import assurance_service as svc

def csvsafe(value):
 s=json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else '' if value is None else str(value)
 return "'"+s if s.lstrip().startswith(('=','+','-','@')) or s.startswith(('\t','\r','\n')) else s

def export_access(store,db,a,e):
 _,m=store.membership(db,a,e.project_id)
 if a.id!=e.actor_id or sorted(m.roles)!=sorted(e.roles):fail(404,'EXPORT_SCOPE_CHANGED','导出不存在或当前岗位范围已改变，请重新申请导出')
 return business_roles(m.roles)

def package(store,db,a,e):
 roles=export_access(store,db,a,e);roles=roles if e.include_sensitive else [r for r in roles if r not in {'财务','商务'}]
 pid=e.project_id;project=store.membership(db,a,pid)[0];root=Path(store.engine.url.database).resolve().parent
 data={'schema_version':1,'project':{'id':pid,'code':project.code,'name':project.name},'scope':{'actor_id':a.id,'roles':roles,'sensitive_confirmed':bool(e.include_sensitive)},'contracts':svc.contracts(db),'metric_versions':['F3-v1','F4-v1','F5-v1','F6-v1'],'generated_at':utcnow()};originals={};total=0
 def add(group,f,path=None):
  nonlocal total
  name=group+'/'+f.id
  if name in originals:return
  p=Path(path or f.path)
  if not p.is_file() or p.is_symlink():fail(409,'EXPORT_ORIGINAL_MISSING','可读原件缺失，未生成成功包')
  content=p.read_bytes()
  if hashlib.sha256(content).hexdigest()!=f.sha256:fail(409,'EXPORT_ORIGINAL_CHANGED','原件校验失败，未生成成功包')
  total+=len(content)
  if total>200*1024*1024 or len(originals)>=5000:fail(422,'EXPORT_LIMIT','单包超过200MB或5000原件，请联系维护人拆分项目范围')
  originals[name]=(content,{'id':f.id,'path':'originals/'+name,'name':f.name,'sha256':f.sha256,'size':len(content)})
 docs=[d for d in db.scalars(select(Document).where(Document.project_id==pid)) if hs.visible(db,d,a,roles)]
 data['documents']=[hs.document_view(db,d,a,roles) for d in docs]
 for d in data['documents']:
  for f in d['draft_files']+[f for v in d['versions'] for f in v['attachments']]:
   obj=db.get(Attachment,f['id']);add('handoff',obj,root/'attachments'/obj.id)
 contracts=[c for c in db.scalars(select(Contract).where(Contract.project_id==pid)) if c.state!='draft' or c.created_by==a.id or set(roles)&{'设计','采购'}];ids={c.id for c in contracts};rows=[r for r in db.scalars(select(MaterialRow).where(MaterialRow.project_id==pid)) if r.contract_id in ids];rowids={r.id for r in rows}
 data['handoff_contracts']=[hs.contract_view(db,c) for c in contracts];data['material_rows']=hs.row_views(db,rows);data['arrivals']=[{k:getattr(x,k) for k in ['id','row_id','quantity','occurred_at','created_by','created_at']} for x in db.scalars(select(Arrival).where(Arrival.project_id==pid)) if x.row_id in rowids]
 data['procurement']=[ps.view(db,o,a,roles) for o in db.scalars(select(PurchaseOrder).where(PurchaseOrder.project_id==pid))]
 for o in data['procurement']:
  for f in o['files']:add('procurement',db.get(PurchaseFile,f['id']))
 data['changes']=[cs.view(db,c,a,roles) for c in db.scalars(select(ChangeCase).where(ChangeCase.project_id==pid))]
 money=bool(set(roles)&{'财务','商务'})
 for c in data['changes']:
  c['files']=[f for f in c['files'] if not f['restricted'] or money]
  if not money:
   for body in [c['draft'],*[v['body'] for v in c['versions']]]:
    body.get('impacts',{}).pop('cost',None)
    if body.get('approval'):body['approval']={k:v for k,v in body['approval'].items() if k not in {'file_ids','basis'}}
  for f in c['files']:add('change',db.get(ChangeFile,f['id']))
 data['trace_templates']=[template_view(db,t) for t in db.scalars(select(TraceTemplate).where(TraceTemplate.project_id==pid))]
 for t in data['trace_templates']:
  for f in t['photos']:add('template-photo',db.get(TemplatePhoto,f['id']))
 data['trace_orders']=[{k:getattr(o,k) for k in ['id','code','version_id','pm_id','factory_id','site_id','quality_id']} for o in db.scalars(select(TraceOrder).where(TraceOrder.project_id==pid))];data['spools']=[ts.view(db,s,roles) for s in db.scalars(select(Spool).where(Spool.project_id==pid))]
 for s in data['spools']:
  if set(roles)&{'项目经理','工厂','现场','质量'}:
   for f in s['files']:add('trace',db.get(TraceFile,f['id']))
  else:
   s['files']=[]
   for r in s['records']:r['file_ids']=[]
 # Cost projections use an explicitly narrowed membership role set for basic exports.
 if '财务' in roles:
  data['cost']=fs.board(store,db,a,pid)
  from .cost_models import CostSource
  for f in data['cost']['files']:add('cost',db.get(CostSource,f['id']))
 elif '项目经理' in roles:
  result=fs.board(store,db,a,pid);data['cost']={'snapshots':[dict(s,body={k:s['body'].get(k) for k in fs.PUBLIC}) for s in result['snapshots']]}
 else:data['cost']={'snapshots':[]}
 data['exceptions']=[svc.case_view(db,x,roles) for x in db.scalars(select(ExceptionCase).where(ExceptionCase.project_id==pid)) if svc.allowed(roles,a,x)]
 for x in data['exceptions']:
  for f in x['files']:add('exception',db.get(ExceptionFile,f['id']))
 relations=[]
 for d in data['documents']:
  for v in d['versions']:
   relations.append({'kind':'version','id':v['id'],'parent_id':d['id'],'source_version_id':v['source_version_id'],'previous_id':v['previous_id']})
 for kind,key,parent in [('procurement','procurement','version_id'),('trace_order','trace_orders','version_id'),('spool','spools','order_id')]:
  for item in data[key]:relations.append({'kind':kind,'id':item['id'],'parent_id':item[parent]})
 for c in data['changes']:
  for v in c['versions']:relations.append({'kind':'change_version','id':v['id'],'parent_id':c['id']})
 for s in data['cost']['snapshots']:relations.append({'kind':'cost_snapshot','id':s['id'],'parent_id':s['previous_id']})
 data['relations']=relations
 archive=io.BytesIO();manifest=[]
 with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
  def put(name,raw):z.writestr(name,raw);manifest.append({'path':name,'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)})
  put('objects.json',json.dumps(data,ensure_ascii=False,sort_keys=True).encode())
  filelist=[v[1] for v in originals.values()]
  for name,raws in [('relations.csv',relations),('originals.csv',filelist)]:
   stream=io.StringIO();keys=list(dict.fromkeys(k for item in raws for k in item)) or ['id'];w=csv.writer(stream);w.writerow(keys)
   for item in raws:w.writerow([csvsafe(item.get(k)) for k in keys])
   put(name,('\ufeff'+stream.getvalue()).encode())
  for _,(raw,meta) in originals.items():put(meta['path'],raw)
  z.writestr('manifest.json',json.dumps({'schema_version':1,'project_id':pid,'actor_id':a.id,'files':manifest,'originals':filelist},ensure_ascii=False).encode())
 return archive.getvalue()

def run_export(store):
 now=utcnow();claim=uid()
 with store.transaction(write=True) as db:
  rows=list(db.scalars(select(EvidenceExport).where(EvidenceExport.state.in_(['queued','running'])).order_by(EvidenceExport.at)))
  e=next((x for x in rows if x.state=='queued' or not x.lease_until or x.lease_until<=now),None)
  if not e:return False
  if e.attempts>=3:e.state='failed';e.error='导出恢复重试已达3次，请重新申请';e.revision+=1;return True
  eid=e.id;e.state='running';e.claim_id=claim;e.lease_until=(datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat();e.attempts+=1;e.revision+=1
 path=None
 try:
  with store.transaction() as db:
   e=db.get(EvidenceExport,eid);a=db.get(Account,e.actor_id)
   if not a or not a.active:fail(403,'ACTOR_REVOKED','账号已停用')
   raw=package(store,db,a,e)
  directory=Path(store.engine.url.database).resolve().parent/'evidence-exports';directory.mkdir(mode=0o700,exist_ok=True);path=directory/(eid+'-'+claim+'.zip');path.write_bytes(raw);path.chmod(0o600)
  with store.transaction(write=True) as db:
   e=db.get(EvidenceExport,eid);a=db.get(Account,e.actor_id);export_access(store,db,a,e)
   if not a.active or e.claim_id!=claim:raise ValueError('claim no longer valid')
   e.path=str(path);e.sha256=hashlib.sha256(raw).hexdigest();e.state='ready';e.claim_id=None;e.lease_until=None;e.completed_at=utcnow();e.revision+=1
 except Exception as err:
  if path:path.unlink(missing_ok=True)
  with store.transaction(write=True) as db:
   e=db.get(EvidenceExport,eid)
   if e.claim_id==claim:e.state='failed';e.error=err.detail.get('message','导出失败') if hasattr(err,'detail') and isinstance(err.detail,dict) else '导出失败，请按原请求核对后重新申请';e.claim_id=None;e.lease_until=None;e.revision+=1
 return True
