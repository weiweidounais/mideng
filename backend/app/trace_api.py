import hashlib,io,zipfile,json
from pathlib import Path
from fastapi import APIRouter,Depends,Request,UploadFile,File,HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from .pilot_service import uid,fail
from .handoff_service import get,role,file_view
from .trace_models import TraceTemplate,TraceOrder,Spool,TraceFile
from .trace_schemas import TemplateCreate,OrderCreate,SpoolCreate,RecordCreate,SpoolAction,Reshape,Mutation,ReshapeOut,TraceBoard,LabelOut
from .handoff_schemas import FileOut
from . import trace_service as svc

def make_trace_router(store,actor,key):
    router=APIRouter(prefix='/projects/{pid}/trace',tags=['管段履历与质量'])
    def scope(db,a,pid):return store.membership(db,a,pid)[1].roles
    def mutate(db,a,pid,name,idem,payload,fn):
        scope(db,a,pid)
        result=store.mutation(db,a,'trace:'+pid+':'+name,idem,payload,fn);db.flush();return result
    @router.get('/board',response_model=TraceBoard)
    def board(pid:str,a=Depends(actor)):
        with store.transaction() as db:
            roles=scope(db,a,pid);spools=[svc.view(db,s,roles) for s in db.scalars(select(Spool).where(Spool.project_id==pid).order_by(Spool.created_at.desc()))]
            from .template_photos import template_view
            return {'templates':[template_view(db,t) for t in db.scalars(select(TraceTemplate).where(TraceTemplate.project_id==pid))], 'orders':[{k:getattr(o,k) for k in ['id','code','version_id','pm_id','factory_id','site_id','quality_id','created_at']} for o in db.scalars(select(TraceOrder).where(TraceOrder.project_id==pid))], 'spools':spools,'metrics':svc.metrics(spools)}
    @router.post('/templates',response_model=Mutation)
    def template(pid:str,b:TemplateCreate,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:return mutate(db,a,pid,'template',idem,b.model_dump(mode='json'),lambda:svc.template(store,db,a,pid,b,r.state.request_id))
    @router.post('/orders',response_model=Mutation)
    def order(pid:str,b:OrderCreate,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:return mutate(db,a,pid,'order',idem,b.model_dump(mode='json'),lambda:svc.order(store,db,a,pid,b,r.state.request_id))
    @router.post('/spools',response_model=Mutation)
    def spool(pid:str,b:SpoolCreate,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:return mutate(db,a,pid,'spool',idem,b.model_dump(mode='json'),lambda:svc.spool(store,db,a,pid,b,r.state.request_id))
    @router.post('/spools/{sid}/records',response_model=Mutation)
    def record(pid:str,sid:str,b:RecordCreate,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            scope(db,a,pid);s=get(db,Spool,pid,sid);return mutate(db,a,pid,'record:'+sid,idem,b.model_dump(mode='json'),lambda:svc.record(store,db,a,s,b,r.state.request_id))
    @router.post('/spools/{sid}/actions',response_model=Mutation|LabelOut)
    def action(pid:str,sid:str,b:SpoolAction,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            scope(db,a,pid);s=get(db,Spool,pid,sid);return mutate(db,a,pid,'action:'+sid,idem,b.model_dump(mode='json'),lambda:svc.act(store,db,a,s,b,r.state.request_id))
    @router.post('/reshape',response_model=ReshapeOut)
    def reshape(pid:str,b:Reshape,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:return mutate(db,a,pid,'reshape',idem,b.model_dump(mode='json'),lambda:svc.reshape(store,db,a,pid,b,r.state.request_id))
    @router.get('/spools/{sid}/qr')
    def qr(pid:str,sid:str,r:Request,a=Depends(actor)):
        with store.transaction() as db:scope(db,a,pid);s=get(db,Spool,pid,sid)
        import qrcode
        import qrcode.image.svg
        data=qrcode.make(str(r.base_url)+'?spool='+s.id,image_factory=qrcode.image.svg.SvgPathFillImage)
        return Response(data.to_string(),media_type='image/svg+xml',headers={'Content-Disposition':'inline'})
    @router.post('/spools/{sid}/files',response_model=FileOut)
    async def upload(pid:str,sid:str,r:Request,file:UploadFile=File(...),a=Depends(actor),idem=Depends(key)):
        def allowed(db):
            scope(db,a,pid);s=get(db,Spool,pid,sid);o=get(db,TraceOrder,pid,s.order_id);roles=scope(db,a,pid)
            if not any(a.id==aid and role in roles for aid,role in [(o.factory_id,'工厂'),(o.site_id,'现场'),(o.quality_id,'质量')]):fail(403,'ASSIGNED_ONLY','仅指定工厂/现场/质量可上传原件')
            if s.state in svc.END:fail(409,'SPOOL_ENDED','已结束对象不可新增原件')
            return s
        with store.transaction() as db:allowed(db)
        name=file.filename or '';ext=Path(name).suffix.lower()
        media={'.pdf':'application/pdf','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.txt':'text/plain','.md':'text/plain','.json':'application/json','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
        if not name or len(name)>180 or Path(name).name!=name or any(x in name for x in ['\\','\x00','/']):fail(422,'UNSAFE_FILENAME','文件名无效')
        if ext not in media:fail(422,'FILE_TYPE','请上传PDF、图片、docx/xlsx或UTF-8文本原件')
        content=await file.read(20*1024*1024+1)
        if not content or len(content)>20*1024*1024:fail(422,'FILE_SIZE','原件须非空且不超过20MB')
        try:
            if ext in {'.md','.txt','.json'}:
                if '\x00' in content.decode('utf-8-sig'):raise ValueError()
                if ext=='.json' and not isinstance(json.loads(content),dict):raise ValueError()
            elif ext=='.pdf':
                import pymupdf
                with pymupdf.open(stream=content,filetype='pdf') as pdf:
                    if not content.startswith(b'%PDF-') or pdf.is_encrypted or pdf.page_count<1:raise ValueError()
            elif ext in {'.png','.jpg','.jpeg'}:
                from .image_validation import validate_camera_image
                validate_camera_image(content,ext)
            else:
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    names=z.namelist();expected='word/document.xml' if ext=='.docx' else 'xl/workbook.xml'
                    if expected not in names or '[Content_Types].xml' not in names or any('vba' in n.lower() for n in names) or sum(i.file_size for i in z.infolist())>100*1024*1024 or any(i.flag_bits&1 for i in z.infolist()):raise ValueError()
                    if z.testzip() is not None:raise ValueError()
        except HTTPException:raise
        except Exception:fail(422,'FILE_CONTENT','文件真实格式或内容无效')
        directory=Path(store.engine.url.database).resolve().parent/'trace-originals';directory.mkdir(mode=0o700,exist_ok=True);fid=uid();path=directory/fid;written=False
        try:
            with store.transaction(write=True) as db:
                s=allowed(db)
                def write():
                    nonlocal written
                    with path.open('xb') as f:f.write(content)
                    path.chmod(0o600);written=True
                    f=TraceFile(id=fid,project_id=pid,spool_id=sid,name=name,sha256=hashlib.sha256(content).hexdigest(),size=len(content),media_type=media[ext],path=str(path),created_by=a.id);db.add(f);db.flush();store.audit(db,a,'trace.file',fid,s.revision,r.state.request_id,pid);return file_view(f)
                return mutate(db,a,pid,'file:'+sid,idem,{'name':name,'hash':hashlib.sha256(content).hexdigest()},write)
        except BaseException:
            if written:path.unlink(missing_ok=True)
            raise
    @router.get('/files/{fid}')
    def download(pid:str,fid:str,preview:bool=False,a=Depends(actor)):
        with store.transaction() as db:
            scope(db,a,pid);f=get(db,TraceFile,pid,fid);s=get(db,Spool,pid,f.spool_id);svc.originals(db,s,[fid]);data=Path(f.path).read_bytes()
            from urllib.parse import quote
            return Response(data,media_type=f.media_type,headers={'Content-Disposition':("inline" if preview and f.media_type in {"image/png","image/jpeg","application/pdf"} else "attachment")+"; filename*=UTF-8''"+quote(f.name)})
    from .template_photos import make_photo_router
    router.include_router(make_photo_router(store,actor,key))
    return router
