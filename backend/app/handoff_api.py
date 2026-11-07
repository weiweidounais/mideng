from .pilot_service import business_roles
import hashlib,io,json,os,tempfile,zipfile
from pathlib import Path
from typing import Literal
from fastapi import APIRouter,Depends,Request,UploadFile,File,Form
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy import select
from PIL import Image
from .pilot_models import Membership,Account
from .pilot_service import uid,fail
from .handoff_models import Document,Version,Contract,MaterialRow,Arrival,Attachment,BusinessEvent,Issue
from .handoff_schemas import DocCreate,DocPatch,Revision,Publish,Withdraw,ContractCreate,ContractAction,RowPatch,ArrivalCreate,DocOut,ContractOut,RowOut,FileOut,BoardOut,BomLine,BomPreviewOut
from . import handoff_service as service


def make_handoff_router(store,actor,key):
    router=APIRouter(prefix='/projects/{pid}/handoff',tags=['需求与交接'])

    def scope(db,a,pid):return business_roles(store.membership(db,a,pid)[1].roles)

    def readable_doc(db,a,pid,oid):
        roles=scope(db,a,pid);d=service.get(db,Document,pid,oid)
        if not service.visible(db,d,a,roles):fail(404,'NOT_ACCESSIBLE','对象不存在或无访问权限')
        return d

    def mutate(db,a,pid,action,idem,b,execute):
        result=store.mutation(db,a,'handoff:'+pid+':'+action,idem,b,execute)
        db.flush();service.reconcile(db,pid);db.flush()
        return result

    @router.get('/board',response_model=BoardOut)
    def board(pid:str,a=Depends(actor)):
        with store.transaction() as db:
            roles=scope(db,a,pid)
            docs=[d for d in db.scalars(select(Document).where(Document.project_id==pid).order_by(Document.created_at.desc())) if service.visible(db,d,a,roles)]
            contracts=[c for c in db.scalars(select(Contract).where(Contract.project_id==pid)) if c.state!='draft' or c.created_by==a.id or set(roles).intersection({'设计','采购'})]
            contract_ids={c.id for c in contracts};doc_ids={d.id for d in docs}
            rows=[r for r in db.scalars(select(MaterialRow).where(MaterialRow.project_id==pid)) if r.contract_id in contract_ids];row_ids={r.id for r in rows}
            objects=doc_ids|contract_ids|row_ids
            issues=[]
            stored={(v.object_id,v.rule):v for v in db.scalars(select(Issue).where(Issue.project_id==pid))}
            # Clock-based labels remain correct between minute scans; GET never changes business state.
            for oid,rule,owner,title in service.issue_candidates(db,pid):
                if oid not in objects or (owner!=a.id and not set(roles).intersection({'项目经理'})):continue
                v=stored.get((oid,rule));issues.append(dict(id=v.id if v else hashlib.sha256((pid+oid+rule).encode()).hexdigest()[:32],object_id=oid,rule=rule,owner_id=owner,title=title,active=True,detected_at=v.detected_at if v else None,closed_at=None))
            return dict(documents=[service.document_view(db,d,a,roles) for d in docs],contracts=[service.contract_view(db,c) for c in contracts],
                rows=service.row_views(db,rows),arrivals=[{k:getattr(v,k) for k in ['id','row_id','quantity','occurred_at','created_by','created_at']} for v in db.scalars(select(Arrival).where(Arrival.project_id==pid)) if v.row_id in row_ids],
                issues=issues,events=[{k:getattr(v,k) for k in ['id','object_id','action','body','actor_id','at']} for v in db.scalars(select(BusinessEvent).where(BusinessEvent.project_id==pid).order_by(BusinessEvent.at.desc()).limit(300)) if v.object_id in objects])

    @router.post('/documents',response_model=DocOut)
    def create(pid:str,b:DocCreate,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            service.role(store,db,a,pid,service.EDIT[b.kind])
            return mutate(db,a,pid,'document.create',idem,b.model_dump(mode='json'),lambda:service.doc_create(store,db,a,pid,b,r.state.request_id))

    @router.get('/documents/{oid}',response_model=DocOut)
    def document(pid:str,oid:str,a=Depends(actor)):
        with store.transaction() as db:
            d=readable_doc(db,a,pid,oid);return service.document_view(db,d,a,scope(db,a,pid))

    @router.patch('/documents/{oid}',response_model=DocOut)
    def patch(pid:str,oid:str,b:DocPatch,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            d=readable_doc(db,a,pid,oid);service.role(store,db,a,pid,service.EDIT[d.kind])
            return mutate(db,a,pid,'document.edit:'+oid,idem,b.model_dump(mode='json'),lambda:service.doc_patch(store,db,a,pid,d,b,r.state.request_id))

    @router.post('/documents/{oid}/revise',response_model=DocOut)
    def revise(pid:str,oid:str,b:Revision,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            d=readable_doc(db,a,pid,oid);service.role(store,db,a,pid,service.EDIT[d.kind])
            return mutate(db,a,pid,'document.revise:'+oid,idem,b.model_dump(mode='json'),lambda:service.revise(store,db,a,pid,d,b,r.state.request_id))

    @router.post('/documents/{oid}/publish',response_model=DocOut)
    def publish(pid:str,oid:str,b:Publish,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            d=readable_doc(db,a,pid,oid);service.role(store,db,a,pid,{'商务'} if d.kind=='requirement' else {'设计'})
            return mutate(db,a,pid,'document.publish:'+oid,idem,b.model_dump(mode='json'),lambda:service.publish(store,db,a,pid,d,b,r.state.request_id))

    @router.post('/documents/{oid}/withdraw',response_model=DocOut)
    def withdraw(pid:str,oid:str,b:Withdraw,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            d=readable_doc(db,a,pid,oid);service.role(store,db,a,pid,{'商务'} if d.kind=='requirement' else {'设计'})
            return mutate(db,a,pid,'document.withdraw:'+oid,idem,b.model_dump(mode='json'),lambda:service.withdraw(store,db,a,pid,d,b,r.state.request_id))

    @router.post('/contracts',response_model=ContractOut)
    def contract_create(pid:str,b:ContractCreate,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            service.role(store,db,a,pid,{'设计'})
            return mutate(db,a,pid,'contract.create',idem,b.model_dump(mode='json'),lambda:service.create_contract(store,db,a,pid,b,r.state.request_id))

    @router.post('/contracts/{oid}/actions',response_model=ContractOut)
    def contract_action(pid:str,oid:str,b:ContractAction,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            scope(db,a,pid);c=service.get(db,Contract,pid,oid)
            if b.action in {'accept','return','close'}:service.recipient(store,db,a,pid,c)
            else:service.role(store,db,a,pid,{'设计','项目经理'} if b.action in {'pause','resume','cancel','reschedule'} else {'设计'})
            return mutate(db,a,pid,'contract.action:'+oid,idem,b.model_dump(mode='json'),lambda:service.contract_action(store,db,a,pid,c,b,r.state.request_id))

    @router.patch('/rows/{oid}',response_model=RowOut)
    def row_patch(pid:str,oid:str,b:RowPatch,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            scope(db,a,pid);v=service.get(db,MaterialRow,pid,oid);service.recipient(store,db,a,pid,service.get(db,Contract,pid,v.contract_id))
            return mutate(db,a,pid,'row.edit:'+oid,idem,b.model_dump(mode='json'),lambda:service.row_patch(store,db,a,pid,v,b,r.state.request_id))

    @router.post('/rows/{oid}/arrivals',response_model=RowOut)
    def arrival(pid:str,oid:str,b:ArrivalCreate,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            scope(db,a,pid);v=service.get(db,MaterialRow,pid,oid);service.recipient(store,db,a,pid,service.get(db,Contract,pid,v.contract_id))
            return mutate(db,a,pid,'row.arrival:'+oid,idem,b.model_dump(mode='json'),lambda:service.arrival_create(store,db,a,pid,v,b,r.state.request_id))

    def file_dir():
        # Same isolated data root as the app, including the verifier's temporary root.
        return Path(store.engine.url.database).resolve().parent/'attachments'

    @router.post('/bom-preview',response_model=BomPreviewOut)
    async def bom_preview(pid:str,file:UploadFile=File(...),a=Depends(actor)):
        with store.transaction() as db:service.role(store,db,a,pid,{'项目经理','设计'})
        import csv
        content=await file.read(20*1024*1024+1)
        if len(content)>20*1024*1024:fail(422,'FILE_SIZE','料表不能超过20MB')
        try:
            reader=csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
            aliases={'物料':'material','规格':'spec','数量':'quantity','单位':'unit','需用日期':'need_by'}
            fields=reader.fieldnames or []
            normalized=[aliases.get(x.strip(),x.strip()) for x in fields]
            if set(normalized)!=set(aliases.values()) or len(normalized)!=5:fail(422,'CSV_HEADER','列须为：物料、规格、数量、单位、需用日期')
            rows=[];errors=[]
            for index,values in enumerate(reader,2):
                if index>5001:fail(422,'ROW_LIMIT','一批最多5000行，请拆分')
                data={aliases.get(k.strip(),k.strip()):v for k,v in values.items() if k is not None}
                if None in values or any(v is None or str(v).lstrip().startswith(('=','+','@')) for v in data.values()):
                    errors.append({'row':index,'field':'row','message':'列数不符或包含公式，请提供确定文本/数值'});continue
                try:rows.append(BomLine.model_validate(data).model_dump(mode='json'))
                except ValidationError as e:
                    for item in e.errors():errors.append({'row':index,'field':'.'.join(map(str,item['loc'])),'message':item['msg']})
            if not rows and not errors:fail(422,'EMPTY_CSV','料表没有数据行')
            return {'rows':rows,'errors':errors}
        except UnicodeDecodeError:fail(422,'CSV_ENCODING','请使用UTF-8 CSV料表')
        except csv.Error:fail(422,'CSV_FORMAT','CSV格式无法解析')

    @router.post('/files',response_model=FileOut)
    async def upload(pid:str,r:Request,kind:Literal['requirement','scheme']=Form(...),file:UploadFile=File(...),a=Depends(actor),idem=Depends(key)):
        # Reject before reading a body into application memory.
        with store.transaction() as db:service.role(store,db,a,pid,service.EDIT[kind])
        name=file.filename or ''
        if not name or len(name)>180 or Path(name).name!=name or any(x in name for x in ['\\','\x00','/']):fail(422,'UNSAFE_FILENAME','文件名无效')
        content=await file.read(20*1024*1024+1)
        if not content or len(content)>20*1024*1024:fail(422,'FILE_SIZE','附件须为非空且不超过20MB')
        suffix=Path(name).suffix.lower();media={'pdf':'application/pdf','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg','txt':'text/plain','md':'text/plain','csv':'text/csv'}
        ext=suffix[1:]
        if ext not in media:fail(422,'FILE_TYPE','仅支持PDF、docx、xlsx、图片及UTF-8文本附件')
        try:
            if ext in {'txt','md','csv'}:
                text=content.decode('utf-8-sig')
                if '\x00' in text:raise ValueError()
            elif ext=='pdf':
                import fitz
                if not content.startswith(b'%PDF-'):raise ValueError()
                with fitz.open(stream=content,filetype='pdf') as pdf:
                    if pdf.is_encrypted or pdf.page_count<1:raise ValueError()
            elif ext in {'docx','xlsx'}:
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    names=z.namelist()
                    if sum(x.file_size for x in z.infolist())>100*1024*1024 or any('vbaproject' in x.lower() for x in names):raise ValueError()
                    if ('word/document.xml' if ext=='docx' else 'xl/workbook.xml') not in names:raise ValueError()
            else:
                with Image.open(io.BytesIO(content)) as image:
                    if image.format not in ({'PNG'} if ext=='png' else {'JPEG'}):raise ValueError()
                    image.verify()
        except Exception:fail(422,'FILE_CONTENT','实际内容与文件类型不符，或文件不可安全读取')
        digest=hashlib.sha256(content).hexdigest();written=[]
        try:
            with store.transaction(write=True) as db:
                service.role(store,db,a,pid,service.EDIT[kind])
                def write():
                    fid=uid();folder=file_dir();folder.mkdir(parents=True,exist_ok=True,mode=0o700)
                    target=folder/fid
                    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(fd,'wb') as f:f.write(content)
                    written.append(target)
                    item=Attachment(id=fid,project_id=pid,kind=kind,name=name,media_type=media[ext],size=len(content),sha256=digest,created_by=a.id)
                    db.add(item);db.flush();service.event(store,db,a,pid,fid,'file.upload',1,r.state.request_id,{'sha256':digest,'size':len(content)})
                    return service.file_view(item)
                return mutate(db,a,pid,'file.upload',idem,{'kind':kind,'name':name,'sha256':digest},write)
        except BaseException:
            for path in written:path.unlink(missing_ok=True)
            raise

    @router.get('/files/{fid}')
    def download(pid:str,fid:str,a=Depends(actor)):
        with store.transaction() as db:
            roles=scope(db,a,pid);f=service.get(db,Attachment,pid,fid)
            formal=any(any(item['id']==fid for item in v.attachments) for v in db.scalars(select(Version).where(Version.project_id==pid)))
            if f.created_by!=a.id and not set(roles).intersection(service.EDIT[f.kind]) and not formal:fail(404,'NOT_ACCESSIBLE','附件不存在或无访问权限')
            path=file_dir()/f.id
            if not path.is_file():fail(404,'FILE_MISSING','附件原件待补充')
            data=path.read_bytes()
            if hashlib.sha256(data).hexdigest()!=f.sha256:fail(409,'FILE_INTEGRITY','附件原件校验失败，请联系维护人')
            from urllib.parse import quote
            return Response(data,media_type=f.media_type,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(f.name)})

    return router
