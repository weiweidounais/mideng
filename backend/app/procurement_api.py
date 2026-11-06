import hashlib,io,os,zipfile
from pathlib import Path
from typing import Literal
from fastapi import APIRouter,Depends,Request,UploadFile,File,Form,HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from . import procurement_service as svc
from .procurement_models import PurchaseOrder,PurchaseFile
from .procurement_schemas import ProcurementBoard,ProcurementMutation,PurchaseCreate,PurchaseAction
from .handoff_schemas import FileOut
from .handoff_service import get,role,file_view
from .pilot_service import uid,fail


def make_procurement_router(store,actor,key):
    router=APIRouter(prefix='/projects/{pid}/procurement',tags=['采购闭环v2'])
    def scope(db,a,pid):return store.membership(db,a,pid)[1].roles
    def mutate(db,a,pid,name,idem,payload,fn):
        result=store.mutation(db,a,'procurement:'+pid+':'+name,idem,payload,fn)
        db.flush()
        from .handoff_service import reconcile
        reconcile(db,pid)
        return result

    @router.get('/board',response_model=ProcurementBoard)
    def board(pid:str,a=Depends(actor)):
        with store.transaction() as db:
            roles=scope(db,a,pid)
            return {'orders':[svc.view(db,o,a,roles) for o in db.scalars(select(PurchaseOrder).where(PurchaseOrder.project_id==pid).order_by(PurchaseOrder.created_at.desc()))]}

    @router.post('/orders',response_model=ProcurementMutation)
    def create(pid:str,b:PurchaseCreate,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            role(store,db,a,pid,{'项目经理'})
            return mutate(db,a,pid,'create',idem,b.model_dump(mode='json'),lambda:svc.create(store,db,a,pid,b,r.state.request_id))

    @router.post('/orders/{oid}/actions',response_model=ProcurementMutation)
    def action(pid:str,oid:str,b:PurchaseAction,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            scope(db,a,pid);o=get(db,PurchaseOrder,pid,oid)
            required={'accept_purchase':{'采购'},'return_request':{'采购'},'resubmit_request':{'项目经理'},'submit_result':{'采购'},'approve_purchase':{'项目经理'},'reject_purchase':{'项目经理'},'arrival':{'采购','质量'},'pass_quality':{'质量'},'fail_quality':{'质量'},'rectify':{'采购'},'archive':{'商务'}}
            role(store,db,a,pid,required[b.action])
            return mutate(db,a,pid,'action:'+oid,idem,b.model_dump(mode='json'),lambda:svc.action(store,db,a,pid,o,b,r.state.request_id))

    @router.post('/orders/{oid}/files',response_model=FileOut)
    async def upload(pid:str,oid:str,r:Request,purpose:Literal['quality','archive']=Form(...),file:UploadFile=File(...),a=Depends(actor),idem=Depends(key)):
        with store.transaction() as db:
            roles=scope(db,a,pid);o=get(db,PurchaseOrder,pid,oid)
            if o.state=='archived':fail(409,'ARCHIVE_IMMUTABLE','已归档采购单原件不可追加或覆盖')
            if purpose=='archive':
                if '商务' not in roles or a.id!=o.commerce_id:fail(403,'RECIPIENT_ONLY','仅指定商务可上传采购合同原件')
            elif not ((a.id==o.quality_id and '质量' in roles) or (a.id==o.purchase_id and '采购' in roles)):
                fail(403,'RECIPIENT_ONLY','仅指定质量或采购可上传验收/整改证据')
        name=file.filename or '';ext=Path(name).suffix.lower()
        media={'.pdf':'application/pdf','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.txt':'text/plain','.md':'text/plain','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
        if not name or len(name)>180 or Path(name).name!=name or any(x in name for x in ['\\','\x00','/']):fail(422,'UNSAFE_FILENAME','文件名无效')
        if ext not in media:fail(422,'FILE_TYPE','请上传PDF、图片、docx/xlsx或UTF-8文本原件')
        content=await file.read(20*1024*1024+1)
        if not content or len(content)>20*1024*1024:fail(422,'FILE_SIZE','原件须非空且不超过20MB')
        try:
            if ext in {'.md','.txt'}:
                if '\x00' in content.decode('utf-8-sig'):raise ValueError()
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
        directory=Path(store.engine.url.database).resolve().parent/'procurement-originals';directory.mkdir(mode=0o700,exist_ok=True)
        fid=uid();path=directory/fid;written=False
        try:
            with store.transaction(write=True) as db:
                scope(db,a,pid);o=get(db,PurchaseOrder,pid,oid)
                if o.state=='archived':fail(409,'ARCHIVE_IMMUTABLE','已归档原件不可追加')
                roles=scope(db,a,pid)
                if purpose=='archive':
                    if '商务' not in roles or a.id!=o.commerce_id:fail(403,'RECIPIENT_ONLY','仅指定商务可上传采购合同原件')
                elif not ((a.id==o.quality_id and '质量' in roles) or (a.id==o.purchase_id and '采购' in roles)):
                    fail(403,'RECIPIENT_ONLY','仅指定质量或采购可上传证据')
                def write():
                    nonlocal written
                    with path.open('xb') as output:output.write(content)
                    path.chmod(0o600);written=True
                    f=PurchaseFile(id=fid,project_id=pid,order_id=oid,purpose=purpose,name=name,sha256=hashlib.sha256(content).hexdigest(),size=len(content),media_type=media[ext],path=str(path),created_by=a.id)
                    db.add(f);db.flush();store.audit(db,a,'procurement.file.'+purpose,f.id,o.revision,r.state.request_id,pid)
                    return file_view(f)
                return mutate(db,a,pid,'file.'+purpose+':'+oid,idem,{'name':name,'purpose':purpose,'sha256':hashlib.sha256(content).hexdigest()},write)
        except BaseException:
            if written:path.unlink(missing_ok=True)
            raise

    @router.get('/files/{fid}')
    def download(pid:str,fid:str,a=Depends(actor)):
        with store.transaction() as db:
            roles=scope(db,a,pid);f=get(db,PurchaseFile,pid,fid)
            if f.purpose=='archive' and not set(roles)&{'商务','财务'}:fail(404,'NOT_ACCESSIBLE','原件不存在或无访问权限')
            path=Path(f.path)
            if not path.is_file():fail(404,'ORIGINAL_MISSING','原件缺失')
            content=path.read_bytes()
            if hashlib.sha256(content).hexdigest()!=f.sha256:fail(409,'ORIGINAL_CHANGED','原件校验失败')
            from urllib.parse import quote
            return Response(content,media_type=f.media_type,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(f.name)})
    return router
