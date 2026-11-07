from .pilot_service import business_roles
import hashlib,io
from pathlib import Path
from fastapi import APIRouter,Depends,Request,UploadFile,File
from fastapi.responses import Response
from .pilot_service import uid,fail
from .handoff_service import get,file_view
from .assurance_models import ExceptionFile,EvidenceExport
from .assurance_schemas import ExceptionAction,ExportCreate,Mutation,BoardOut,ExportOut,ContractOut
from .handoff_schemas import FileOut
from . import assurance_service as svc
from .evidence_export import export_access

def make_assurance_router(store,actor,key):
 router=APIRouter(prefix='/projects/{pid}/assurance',tags=['异常与证据'])
 def mutate(db,a,pid,name,idem,body,fn):return store.mutation(db,a,'assurance:'+pid+':'+name,idem,body,fn)
 @router.get('/board',response_model=BoardOut)
 def board(pid:str,a=Depends(actor)):
  with store.transaction(write=True) as db:store.membership(db,a,pid);svc.reconcile(db,pid);db.flush();return svc.board(store,db,a,pid)
 @router.get('/contracts',response_model=list[ContractOut])
 def contracts(pid:str,a=Depends(actor)):
  with store.transaction() as db:store.membership(db,a,pid);return svc.contracts(db)
 @router.post('/exceptions/{eid}/actions',response_model=Mutation)
 def action(pid:str,eid:str,b:ExceptionAction,r:Request,a=Depends(actor),idem=Depends(key)):
  with store.transaction(write=True) as db:
   e,roles=svc.access(store,db,a,pid,eid);svc.reconcile(db,pid);db.flush()
   return mutate(db,a,pid,'exception:'+eid,idem,b.model_dump(mode='json'),lambda:svc.act(store,db,a,e,roles,b,r.state.request_id))
 @router.post('/exceptions/{eid}/files',response_model=FileOut)
 async def file(pid:str,eid:str,r:Request,file:UploadFile=File(...),a=Depends(actor),idem=Depends(key)):
  with store.transaction() as db:
   e,roles=svc.access(store,db,a,pid,eid)
   if not svc.managed(roles,e):fail(403,'EXCEPTION_MANAGER','仅异常管理岗位上传批准依据')
  name=file.filename or '';ext=Path(name).suffix.lower();media={'.md':'text/plain','.txt':'text/plain','.pdf':'application/pdf','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg'}
  if not name or len(name)>180 or Path(name).name!=name or any(c in name for c in ['\\','/']) or any(ord(c)<32 for c in name) or ext not in media:fail(422,'FILE_TYPE','批准依据使用安全文件名的PDF/图片/UTF-8文本')
  raw=await file.read(20*1024*1024+1)
  if not raw or len(raw)>20*1024*1024:fail(422,'FILE_SIZE','批准依据须非空且不超过20MB')
  try:
   if ext in {'.md','.txt'}:
    if '\x00' in raw.decode('utf-8-sig'):raise ValueError()
   elif ext=='.pdf':
    import pymupdf
    with pymupdf.open(stream=raw,filetype='pdf') as doc:
     if not raw.startswith(b'%PDF-') or doc.is_encrypted or doc.page_count<1:raise ValueError()
   else:
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as pic:
     if pic.format!=('PNG' if ext=='.png' else 'JPEG'):raise ValueError()
     pic.verify()
  except Exception:fail(422,'FILE_CONTENT','批准依据真实格式无效')
  written=[]
  try:
   with store.transaction(write=True) as db:
    e,roles=svc.access(store,db,a,pid,eid)
    if not svc.managed(roles,e):fail(403,'EXCEPTION_MANAGER','岗位已变化')
    def save():
     fid=uid();directory=Path(store.engine.url.database).resolve().parent/'assurance-originals';directory.mkdir(mode=0o700,exist_ok=True);path=directory/fid
     with path.open('xb') as f:written.append(path);f.write(raw)
     path.chmod(0o600);obj=ExceptionFile(id=fid,project_id=pid,exception_id=eid,name=name,path=str(path),sha256=hashlib.sha256(raw).hexdigest(),size=len(raw),media_type=media[ext],created_by=a.id);db.add(obj);db.flush();store.audit(db,a,'assurance.evidence',eid,e.revision,r.state.request_id,pid);return file_view(obj)
    return mutate(db,a,pid,'file:'+eid,idem,{'name':name,'sha256':hashlib.sha256(raw).hexdigest()},save)
  except BaseException:
   for path in written:path.unlink(missing_ok=True)
   raise
 @router.get('/files/{fid}')
 def download_file(pid:str,fid:str,a=Depends(actor)):
  with store.transaction() as db:
   f=get(db,ExceptionFile,pid,fid);svc.access(store,db,a,pid,f.exception_id);raw=svc.original(f)
   return Response(raw,media_type=f.media_type,headers={'Content-Disposition':'attachment'})
 @router.post('/exports',response_model=Mutation)
 def create_export(pid:str,b:ExportCreate,r:Request,a=Depends(actor),idem=Depends(key)):
  with store.transaction(write=True) as db:
   _,m=store.membership(db,a,pid)
   if not b.confirmed:fail(422,'EXPORT_CONFIRM','请明确确认本项目授权范围的本机证据导出')
   if b.include_sensitive and not set(business_roles(m.roles))&{'财务','商务'}:fail(403,'SENSITIVE_SCOPE','敏感导出须具有对应财务/商务岗位')
   def save():
    e=EvidenceExport(id=uid(),project_id=pid,actor_id=a.id,roles=sorted(m.roles),include_sensitive=int(b.include_sensitive));db.add(e);db.flush();store.audit(db,a,'assurance.export',e.id,1,r.state.request_id,pid);return {'id':e.id,'revision':1}
   return mutate(db,a,pid,'export',idem,b.model_dump(mode='json'),save)
 @router.get('/exports/{eid}',response_model=ExportOut)
 def export_status(pid:str,eid:str,a=Depends(actor)):
  with store.transaction() as db:e=get(db,EvidenceExport,pid,eid);export_access(store,db,a,e);return svc.export_view(e)
 @router.get('/exports/{eid}/download')
 def download_export(pid:str,eid:str,a=Depends(actor)):
  with store.transaction() as db:
   e=get(db,EvidenceExport,pid,eid);export_access(store,db,a,e)
   if e.state!='ready':fail(409,'EXPORT_NOT_READY','证据任务尚未成功，请查看状态')
   p=Path(e.path)
   if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=e.sha256:fail(409,'EXPORT_INTEGRITY','导出文件缺失或校验失败，请重新申请')
   return Response(p.read_bytes(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename=project-evidence-'+eid+'.zip'})
 return router
