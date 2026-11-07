from .pilot_service import business_roles
import hashlib,io,zipfile
from pathlib import Path
from fastapi import APIRouter,Depends,Request,UploadFile,File,Form
from fastapi.responses import Response
from sqlalchemy import select
from .pilot_service import uid,fail
from .handoff_service import get,role,file_view
from .change_models import ChangeCase,ChangeFile
from .change_schemas import ChangeCreate,ChangeAction,ChangeMutation,ChangeBoard,ChangeFileOut
from . import change_service as svc

def make_change_router(store,actor,key):
    router=APIRouter(prefix='/projects/{pid}/changes',tags=['变更同步与处置'])
    def scope(db,a,pid):return business_roles(store.membership(db,a,pid)[1].roles)
    def readable(c,a,roles):return bool(c.current_version_id or c.created_by==a.id or set(roles)&{'项目经理','设计','商务','质量','财务'})
    def mutation(db,a,pid,name,idem,payload,fn):
        result=store.mutation(db,a,'change:'+pid+':'+name,idem,payload,fn);db.flush()
        from .handoff_service import reconcile
        reconcile(db,pid);return result
    @router.get('/board',response_model=ChangeBoard)
    def board(pid:str,a=Depends(actor)):
        with store.transaction() as db:
            roles=scope(db,a,pid)
            return {'cases':[svc.view(db,c,a,roles) for c in db.scalars(select(ChangeCase).where(ChangeCase.project_id==pid).order_by(ChangeCase.updated_at.desc())) if readable(c,a,roles)]}
    @router.post('',response_model=ChangeMutation)
    def create(pid:str,b:ChangeCreate,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            role(store,db,a,pid,{'项目经理'})
            return mutation(db,a,pid,'create',idem,b.model_dump(mode='json'),lambda:svc.create(store,db,a,pid,b,r.state.request_id))
    @router.post('/{cid}/actions',response_model=ChangeMutation)
    def action(pid:str,cid:str,b:ChangeAction,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            roles=scope(db,a,pid);c=get(db,ChangeCase,pid,cid)
            if not readable(c,a,roles):fail(404,'NOT_ACCESSIBLE','对象不存在或无访问权限')
            return mutation(db,a,pid,'action:'+cid,idem,b.model_dump(mode='json'),lambda:svc.act(store,db,a,pid,c,b,r.state.request_id))
    @router.post('/{cid}/files',response_model=ChangeFileOut)
    async def upload(pid:str,cid:str,r:Request,purpose:str=Form(...),restricted:bool=Form(False),file:UploadFile=File(...),a=Depends(actor),idem=Depends(key)):
        with store.transaction() as db:
            roles=scope(db,a,pid);c=get(db,ChangeCase,pid,cid)
            if not readable(c,a,roles):fail(404,'NOT_ACCESSIBLE','对象不存在或无访问权限')
            if not set(roles)&{'项目经理','设计','采购','质量','商务','财务'}:fail(403,'EVIDENCE_FORBIDDEN','当前岗位不能上传变更证据')
            if restricted and not set(roles)&{'商务','财务'}:fail(403,'COST_FORBIDDEN','受限原件须由商务/财务上传')
            if c.state in {'closed','cancelled'}:fail(409,'CHANGE_ENDED','已结束变更不可新增原件')
        if purpose not in {'approval','execution'}:fail(422,'FILE_PURPOSE','请选择批准凭据或执行证据用途')
        name=file.filename or '';ext=Path(name).suffix.lower()
        media={'.md':'text/plain','.txt':'text/plain','.pdf':'application/pdf','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
        if not name or len(name)>180 or Path(name).name!=name or any(x in name for x in ['\\','/','\x00']):fail(422,'UNSAFE_FILENAME','文件名无效')
        if ext not in media:fail(422,'FILE_TYPE','仅支持PDF/图片/Office或UTF-8文本原件')
        data=await file.read(20*1024*1024+1)
        if not data or len(data)>20*1024*1024:fail(422,'FILE_SIZE','原件须非空且不超过20MB')
        try:
            if ext in {'.md','.txt'}:
                if '\x00' in data.decode('utf-8-sig'):raise ValueError()
            elif ext=='.pdf':
                import pymupdf
                with pymupdf.open(stream=data,filetype='pdf') as pdf:
                    if not data.startswith(b'%PDF-') or pdf.page_count<1 or pdf.is_encrypted:raise ValueError()
            elif ext in {'.png','.jpg','.jpeg'}:
                from PIL import Image
                with Image.open(io.BytesIO(data)) as pic:
                    if pic.format not in ({'PNG'} if ext=='.png' else {'JPEG'}):raise ValueError()
                    pic.verify()
            else:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    expected='word/document.xml' if ext=='.docx' else 'xl/workbook.xml'
                    if expected not in z.namelist() or '[Content_Types].xml' not in z.namelist() or any('vba' in n.lower() for n in z.namelist()) or sum(x.file_size for x in z.infolist())>100*1024*1024 or any(x.flag_bits&1 for x in z.infolist()) or z.testzip() is not None:raise ValueError()
        except Exception:fail(422,'FILE_CONTENT','原件真实格式或内容无效')
        directory=Path(store.engine.url.database).resolve().parent/'change-originals';directory.mkdir(mode=0o700,exist_ok=True);fid=uid();path=directory/fid;written=False
        try:
            with store.transaction(write=True) as db:
                roles=scope(db,a,pid);c=get(db,ChangeCase,pid,cid)
                if not set(roles)&{'项目经理','设计','采购','质量','商务','财务'} or (restricted and not set(roles)&{'商务','财务'}):fail(403,'EVIDENCE_FORBIDDEN','上传岗位授权已变化')
                if c.state in {'closed','cancelled'}:fail(409,'CHANGE_ENDED','变更已结束')
                def write():
                    nonlocal written
                    with path.open('xb') as f:f.write(data)
                    path.chmod(0o600);written=True
                    f=ChangeFile(id=fid,project_id=pid,case_id=cid,version_id=c.current_version_id,purpose=purpose,restricted=restricted,name=name,sha256=hashlib.sha256(data).hexdigest(),size=len(data),media_type=media[ext],path=str(path),created_by=a.id);db.add(f);db.flush()
                    store.audit(db,a,'change.file',fid,c.revision,r.state.request_id,pid)
                    return file_view(f)|{'restricted':restricted,'purpose':purpose,'version_id':c.current_version_id}
                return mutation(db,a,pid,'file:'+cid,idem,{'name':name,'hash':hashlib.sha256(data).hexdigest(),'purpose':purpose,'restricted':restricted},write)
        except BaseException:
            if written:path.unlink(missing_ok=True)
            raise
    @router.get('/files/{fid}')
    def download(pid:str,fid:str,a=Depends(actor)):
        with store.transaction() as db:
            roles=scope(db,a,pid);f=get(db,ChangeFile,pid,fid)
            if not readable(get(db,ChangeCase,pid,f.case_id),a,roles):fail(404,'NOT_ACCESSIBLE','原件不存在或无访问权限')
            if f.restricted and not set(roles)&{'商务','财务'}:fail(404,'NOT_ACCESSIBLE','原件不存在或无访问权限')
            path=Path(f.path)
            if not path.is_file():fail(404,'ORIGINAL_MISSING','证据原件缺失')
            data=path.read_bytes()
            if hashlib.sha256(data).hexdigest()!=f.sha256:fail(409,'ORIGINAL_CHANGED','原件校验不符')
            from urllib.parse import quote
            return Response(data,media_type=f.media_type,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(f.name)})
    return router
