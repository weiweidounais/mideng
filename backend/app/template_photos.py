"""Immutable template photo originals, linked only by the responsible quality actor."""
import hashlib
from pathlib import Path
from fastapi import APIRouter,Depends,Request,UploadFile,File
from fastapi.responses import Response
from sqlalchemy import select
from .pilot_service import fail,uid
from .handoff_service import get,role,file_view
from .trace_models import TraceTemplate,TemplatePhoto,TemplatePhotoLink
from .trace_schemas import PhotoIds,Mutation
from .handoff_schemas import FileOut

def original(photo):
    p=Path(photo.path)
    if not p.is_file():fail(404,'PHOTO_MISSING','模板照片原件缺失')
    data=p.read_bytes()
    if hashlib.sha256(data).hexdigest()!=photo.sha256:fail(409,'PHOTO_CHANGED','模板照片校验不符')
    return data

def photos(db,tid):
    return [file_view(photo)|{'linked_by':link.actor_id,'linked_at':link.at} for photo,link in db.execute(select(TemplatePhoto,TemplatePhotoLink).join(TemplatePhotoLink,TemplatePhotoLink.photo_id==TemplatePhoto.id).where(TemplatePhotoLink.template_id==tid).order_by(TemplatePhotoLink.at,TemplatePhoto.id))]

def template_view(db,t):
    items=photos(db,t.id)
    return {k:getattr(t,k) for k in ['id','name','scope','welding','pressure','basis','approved_by','approved_at']}|{'photos':items,'photo_ids':[p['id'] for p in items]}

def attach(store,db,a,t,ids,rid):
    role(store,db,a,t.project_id,{'质量'})
    if t.approved_by!=a.id:fail(403,'TEMPLATE_OWNER','仅该模板原确认质量人员可补充照片')
    existing=set(db.scalars(select(TemplatePhotoLink.photo_id).where(TemplatePhotoLink.template_id==t.id)))
    if len(existing|set(ids))>10:fail(422,'PHOTO_LIMIT','每份模板最多10张照片')
    added=[]
    for fid in ids:
        if fid in existing:continue
        p=get(db,TemplatePhoto,t.project_id,fid)
        if p.created_by!=a.id:fail(404,'NOT_ACCESSIBLE','照片不存在或无访问权限')
        if db.scalar(select(TemplatePhotoLink).where(TemplatePhotoLink.photo_id==fid)):fail(422,'PHOTO_LINKED','照片已关联其他模板，请重新上传原件')
        original(p);db.add(TemplatePhotoLink(template_id=t.id,photo_id=fid,actor_id=a.id));added.append(fid)
    if added:store.audit(db,a,'trace.template.photos',t.id,1,rid,t.project_id)
    return {'id':t.id,'revision':1}

def make_photo_router(store,actor,key):
    router=APIRouter()
    @router.post('/template-photos',response_model=FileOut)
    async def upload(pid:str,r:Request,file:UploadFile=File(...),a=Depends(actor),idem=Depends(key)):
        with store.transaction() as db:role(store,db,a,pid,{'质量'})
        name=file.filename or '';ext=Path(name).suffix.lower();formats={'.jpg':('JPEG','image/jpeg'),'.jpeg':('JPEG','image/jpeg'),'.png':('PNG','image/png'),'.webp':('WEBP','image/webp')}
        if not name or len(name)>180 or Path(name).name!=name or any(c in name for c in ['\\','/','\x00']) or any(ord(c)<32 for c in name):fail(422,'UNSAFE_FILENAME','照片文件名无效')
        if ext not in formats:fail(422,'PHOTO_TYPE','照片支持JPG、PNG、WebP格式')
        data=await file.read(10*1024*1024+1)
        if not data or len(data)>10*1024*1024:fail(422,'PHOTO_SIZE','每张照片须非空且不超过10MB')
        from .image_validation import validate_camera_image
        validate_camera_image(data,ext,max_pixels=20_000_000,full_decode=True)
        directory=Path(store.engine.url.database).resolve().parent/'template-photos';directory.mkdir(mode=0o700,exist_ok=True);fid=uid();path=directory/fid;written=False
        try:
            with store.transaction(write=True) as db:
                role(store,db,a,pid,{'质量'})
                def write():
                    nonlocal written
                    with path.open('xb') as f:f.write(data)
                    path.chmod(0o600);written=True
                    p=TemplatePhoto(id=fid,project_id=pid,name=name,sha256=hashlib.sha256(data).hexdigest(),size=len(data),media_type=formats[ext][1],path=str(path),created_by=a.id);db.add(p);db.flush();store.audit(db,a,'trace.template.photo.upload',fid,1,r.state.request_id,pid);return file_view(p)
                return store.mutation(db,a,'trace:'+pid+':template-photo',idem,{'name':name,'sha256':hashlib.sha256(data).hexdigest()},write)
        except BaseException:
            if written:path.unlink(missing_ok=True)
            raise
    @router.post('/templates/{tid}/photos',response_model=Mutation)
    def supplement(pid:str,tid:str,b:PhotoIds,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            role(store,db,a,pid,{'质量'});t=get(db,TraceTemplate,pid,tid)
            if t.approved_by!=a.id:fail(403,'TEMPLATE_OWNER','仅该模板原确认质量人员可补充照片')
            return store.mutation(db,a,'trace:'+pid+':template-photos:'+tid,idem,b.model_dump(mode='json'),lambda:attach(store,db,a,t,b.photo_ids,r.state.request_id))
    @router.get('/template-photos/{fid}')
    def download(pid:str,fid:str,a=Depends(actor)):
        with store.transaction() as db:
            store.membership(db,a,pid);p=get(db,TemplatePhoto,pid,fid);linked=db.scalar(select(TemplatePhotoLink).where(TemplatePhotoLink.photo_id==fid))
            if not linked and p.created_by!=a.id:fail(404,'NOT_ACCESSIBLE','照片不存在或无访问权限')
            data=original(p)
            from urllib.parse import quote
            return Response(data,media_type=p.media_type,headers={'Content-Disposition':"inline; filename*=UTF-8''"+quote(p.name)})
    return router
