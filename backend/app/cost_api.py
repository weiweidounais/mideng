import hashlib,io,zipfile,json
from pathlib import Path
from fastapi import APIRouter,Depends,Request,UploadFile,File,Form
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy import select
from . import cost_service as svc
from .cost_models import CostProfile,CostSource,CostBatch,CostClose
from .cost_schemas import ProfileCreate,UploadMeta,BatchAction,CalendarCreate,BudgetCreate,CloseCreate,CloseAction,Mutation,BatchOut,BoardOut
from .handoff_schemas import FileOut
from .handoff_service import get,file_view
from .pilot_service import uid,fail

def make_cost_router(store,actor,key):
 router=APIRouter(prefix='/projects/{pid}/cost',tags=['成本与月结'])
 def mutate(db,a,pid,name,idem,payload,fn):
  svc.finance(store,db,a,pid);result=store.mutation(db,a,'cost:'+pid+':'+name,idem,payload,fn);db.flush();return result
 @router.get('/board',response_model=BoardOut)
 def board(pid:str,a=Depends(actor)):
  with store.transaction() as db:return svc.board(store,db,a,pid)
 @router.post('/profiles',response_model=Mutation)
 def profile(pid:str,b:ProfileCreate,r:Request,a=Depends(actor),idem=Depends(key)):
  with store.transaction(write=True) as db:return mutate(db,a,pid,'profile',idem,b.model_dump(mode='json'),lambda:svc.profile(store,db,a,pid,b,r.state.request_id))
 @router.post('/calendars',response_model=Mutation)
 def calendar(pid:str,b:CalendarCreate,r:Request,a=Depends(actor),idem=Depends(key)):
  with store.transaction(write=True) as db:return mutate(db,a,pid,'calendar',idem,b.model_dump(mode='json'),lambda:svc.calendar_create(store,db,a,pid,b,r.state.request_id))
 @router.post('/budgets',response_model=Mutation)
 def budget(pid:str,b:BudgetCreate,r:Request,a=Depends(actor),idem=Depends(key)):
  with store.transaction(write=True) as db:return mutate(db,a,pid,'budget',idem,b.model_dump(mode='json'),lambda:svc.budget(store,db,a,pid,b,r.state.request_id))
 @router.get('/batches/{bid}',response_model=BatchOut)
 def batch(pid:str,bid:str,a=Depends(actor)):
  with store.transaction() as db:svc.finance(store,db,a,pid);return svc.batch_view(get(db,CostBatch,pid,bid))
 @router.post('/batches/{bid}/actions',response_model=Mutation)
 def batch_action(pid:str,bid:str,b:BatchAction,r:Request,a=Depends(actor),idem=Depends(key)):
  with store.transaction(write=True) as db:
   svc.finance(store,db,a,pid);row=get(db,CostBatch,pid,bid);return mutate(db,a,pid,'batch:'+bid,idem,b.model_dump(mode='json'),lambda:svc.batch_action(store,db,a,row,b,r.state.request_id))
 @router.post('/closes',response_model=Mutation)
 def close(pid:str,b:CloseCreate,r:Request,a=Depends(actor),idem=Depends(key)):
  with store.transaction(write=True) as db:return mutate(db,a,pid,'close',idem,b.model_dump(mode='json'),lambda:svc.close_create(store,db,a,pid,b,r.state.request_id))
 @router.post('/closes/{cid}/actions',response_model=Mutation)
 def close_action(pid:str,cid:str,b:CloseAction,r:Request,a=Depends(actor),idem=Depends(key)):
  with store.transaction(write=True) as db:
   svc.finance(store,db,a,pid);row=get(db,CostClose,pid,cid);return mutate(db,a,pid,'close:'+cid,idem,b.model_dump(mode='json'),lambda:svc.close_action(store,db,a,row,b,r.state.request_id))
 async def read_file(file,imports=False):
  name=file.filename or '';ext=Path(name).suffix.lower();media={'.csv':'text/csv','.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','.md':'text/plain','.txt':'text/plain','.pdf':'application/pdf','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
  if not name or len(name)>180 or Path(name).name!=name or any(c in name for c in ['\\','/','\x00']) or any(ord(c)<32 for c in name):fail(422,'UNSAFE_FILENAME','源文件名无效')
  if ext not in media or (imports and ext not in {'.csv','.xlsx'}):fail(422,'FILE_TYPE','导入仅支持xlsx/UTF-8 csv，依据支持PDF/图片/Office/文本')
  content=await file.read(20*1024*1024+1)
  if not content or len(content)>20*1024*1024:fail(422,'FILE_SIZE','文件须非空且不超过20MB')
  try:
   if ext in {'.md','.txt','.csv'}:
    if '\x00' in content.decode('utf-8-sig'):raise ValueError()
   elif ext=='.pdf':
    import pymupdf
    with pymupdf.open(stream=content,filetype='pdf') as doc:
     if not content.startswith(b'%PDF-') or doc.is_encrypted or doc.page_count<1:raise ValueError()
   elif ext in {'.png','.jpg','.jpeg'}:
    from PIL import Image
    with Image.open(io.BytesIO(content)) as pic:
     if pic.format not in ({'PNG'} if ext=='.png' else {'JPEG'}):raise ValueError()
     pic.verify()
   else:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
     expected='xl/workbook.xml' if ext=='.xlsx' else 'word/document.xml'
     if expected not in z.namelist() or '[Content_Types].xml' not in z.namelist() or len(z.infolist())>2000 or any('vba' in n.lower() for n in z.namelist()) or sum(x.file_size for x in z.infolist())>100*1024*1024 or any(x.flag_bits&1 for x in z.infolist()) or z.testzip() is not None:raise ValueError()
  except Exception:fail(422,'FILE_CONTENT','源文件真实格式或内容无效')
  return name,content,media[ext]
 def save(db,a,pid,name,data,media,purpose,written):
  fid=uid();directory=Path(store.engine.url.database).resolve().parent/'cost-originals';directory.mkdir(mode=0o700,exist_ok=True);path=directory/fid
  with path.open('xb') as output:written.append(path);output.write(data)
  path.chmod(0o600);f=CostSource(id=fid,project_id=pid,purpose=purpose,name=name,sha256=hashlib.sha256(data).hexdigest(),size=len(data),media_type=media,path=str(path),actor_id=a.id);db.add(f);db.flush();return f,path
 @router.post('/evidence',response_model=FileOut)
 async def evidence(pid:str,r:Request,file:UploadFile=File(...),a=Depends(actor),idem=Depends(key)):
  with store.transaction() as db:svc.finance(store,db,a,pid)
  name,data,media=await read_file(file);written=[]
  try:
   with store.transaction(write=True) as db:
    def write():
     f,path=save(db,a,pid,name,data,media,'evidence',written);svc.event(store,db,a,pid,f.id,'evidence',r.state.request_id);return file_view(f)
    return mutate(db,a,pid,'evidence',idem,{'name':name,'hash':hashlib.sha256(data).hexdigest()},write)
  except BaseException:
   for path in written:path.unlink(missing_ok=True)
   raise
 @router.post('/batches',response_model=Mutation)
 async def upload(pid:str,r:Request,meta:str=Form(...),file:UploadFile=File(...),a=Depends(actor),idem=Depends(key)):
  with store.transaction() as db:svc.finance(store,db,a,pid)
  try:b=UploadMeta.model_validate_json(meta)
  except ValidationError:fail(422,'BATCH_META','请核对项目期间、模式/范围、币种税口径及导出/截止时间')
  name,data,media=await read_file(file,True);payload=b.model_dump(mode='json');sha=hashlib.sha256(data).hexdigest();written=[]
  try:
   with store.transaction(write=True) as db:
    svc.finance(store,db,a,pid);get(db,CostProfile,pid,b.profile_id)
    for bid in b.replace_ids:get(db,CostBatch,pid,bid)
    if b.corrects_batch_id:get(db,CostBatch,pid,b.corrects_batch_id)
    def write():
     for old in db.scalars(select(CostBatch).where(CostBatch.project_id==pid,CostBatch.profile_id==b.profile_id)):
      if old.meta==payload and db.get(CostSource,old.source_id).sha256==sha:return {'id':old.id,'revision':old.revision}
     source,path=save(db,a,pid,name,data,media,'import',written);row=CostBatch(id=uid(),project_id=pid,source_id=source.id,profile_id=b.profile_id,meta=payload,actor_id=a.id);db.add(row);db.flush();svc.event(store,db,a,pid,row.id,'upload',r.state.request_id);return {'id':row.id,'revision':row.revision}
    return mutate(db,a,pid,'upload',idem,{'meta':payload,'sha256':sha},write)
  except BaseException:
   for path in written:path.unlink(missing_ok=True)
   raise
 @router.get('/files/{fid}')
 def download(pid:str,fid:str,a=Depends(actor)):
  with store.transaction() as db:
   svc.finance(store,db,a,pid);f=get(db,CostSource,pid,fid);data=svc.original(f)
   from urllib.parse import quote
   return Response(data,media_type=f.media_type,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(f.name)})
 @router.get('/template.xlsx')
 def xlsx_template(pid:str,a=Depends(actor)):
  with store.transaction() as db:svc.finance(store,db,a,pid)
  from .cost_import import FIELDS
  import openpyxl
  book=openpyxl.Workbook();sheet=book.active;sheet.title='成本模板';sheet.append(list(FIELDS.values()))
  for col in sheet.columns:sheet.column_dimensions[col[0].column_letter].width=18
  stream=io.BytesIO();book.save(stream);return Response(stream.getvalue(),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename=cost-template.xlsx'})
 @router.get('/template.csv')
 def template(pid:str,a=Depends(actor)):
  with store.transaction() as db:svc.finance(store,db,a,pid)
  from .cost_import import FIELDS
  return Response(('\ufeff'+','.join(FIELDS.values())+'\n').encode('utf-8'),media_type='text/csv',headers={'Content-Disposition':"attachment; filename*=UTF-8''cost-template.csv"})
 return router
