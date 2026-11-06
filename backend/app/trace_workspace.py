"""Additive mobile trace projections; historical endpoints and all write gates stay intact."""
import hashlib,json
from typing import Any,Literal
from fastapi import APIRouter,Depends,Query
from pydantic import BaseModel
from sqlalchemy import select,func,true
from sqlalchemy.orm import defer
from .pilot_service import fail
from .pilot_models import utcnow
from .handoff_service import get,file_view,source_current
from .handoff_models import Document,Version
from .trace_models import Spool,TraceOrder,TraceTemplate,TraceRecord,TraceEvent,TraceFile,TraceWeld
from .trace_schemas import TemplateOut,OrderOut,SpoolOut
from .template_photos import template_view
from . import trace_service as svc
class SpoolItem(BaseModel):id:str;code:str;state:str;revision:int;order_id:str;template_id:str;order_code:str;template_name:str;owner_id:str
class Index(BaseModel):items:list[SpoolItem];total:int;page:int;page_size:int;templates:list[TemplateOut];orders:list[OrderOut];template_total:int;order_total:int
class Detail(SpoolOut):has_shipment:bool;record_total:int;event_total:int;file_total:int;weld_total:int;templates:list[TemplateOut];orders:list[OrderOut];source_document_id:str;source_version_id:str
class History(BaseModel):kind:Literal['records','events','files','welds'];items:list[dict[str,Any]];total:int;page:int;page_size:int;revision:int;dataset_token:str
class Choice(BaseModel):id:str;label:str;revision:int|None=None;order_id:str|None=None;template_id:str|None=None;quality_id:str|None=None;available:bool=True
class Choices(BaseModel):items:list[Choice];total:int;page:int;page_size:int
class Metrics(BaseModel):definition:str;completed_total:int;completed_valid:int;completed_rate:float|None;in_progress_total:int;in_progress_ready:int;scrapped:int;retired:int;checked_at:str

def order_view(o):return {k:getattr(o,k) for k in OrderOut.model_fields}
def make_trace_workspace(store,actor):
 router=APIRouter(prefix='/projects/{pid}/trace',tags=['手机管段与履历'])
 def count(db,cls,pid,sid=None):
  q=select(func.count()).select_from(cls).where(cls.project_id==pid)
  if sid:q=q.where(cls.spool_id==sid)
  return db.scalar(q)
 @router.get('/workspace',response_model=Index)
 def index(pid:str,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=50),query:str=Query('',max_length=80),order_id:str|None=None,template_page:int=Query(1,ge=1),order_page:int=Query(1,ge=1),a=Depends(actor)):
  with store.transaction() as db:
   store.membership(db,a,pid)
   if order_id:get(db,TraceOrder,pid,order_id)
   q=select(Spool,TraceOrder.code,TraceTemplate.name).join(TraceOrder,Spool.order_id==TraceOrder.id).join(TraceTemplate,Spool.template_id==TraceTemplate.id).where(Spool.project_id==pid)
   if query:q=q.where(Spool.code.contains(query,autoescape=True))
   if order_id:q=q.where(Spool.order_id==order_id)
   total=db.scalar(select(func.count()).select_from(q.subquery()));rows=db.execute(q.order_by(Spool.created_at.desc(),Spool.id).offset((page-1)*page_size).limit(page_size))
   items=[dict(id=s.id,code=s.code,state=s.state,revision=s.revision,order_id=s.order_id,template_id=s.template_id,order_code=code,template_name=name,owner_id=svc.owner(db,s)) for s,code,name in rows]
   templates=db.scalars(select(TraceTemplate).where(TraceTemplate.project_id==pid).order_by(TraceTemplate.approved_at.desc(),TraceTemplate.id).offset((template_page-1)*page_size).limit(page_size));orders=db.scalars(select(TraceOrder).where(TraceOrder.project_id==pid).order_by(TraceOrder.created_at.desc(),TraceOrder.id).offset((order_page-1)*page_size).limit(page_size))
   return dict(items=items,total=total,page=page,page_size=page_size,templates=[template_view(db,t) for t in templates],orders=[order_view(o) for o in orders],template_total=count(db,TraceTemplate,pid),order_total=count(db,TraceOrder,pid))
 @router.get('/workspace/spools/{sid}',response_model=Detail)
 def detail(pid:str,sid:str,a=Depends(actor)):
  with store.transaction() as db:
   _,m=store.membership(db,a,pid);s=get(db,Spool,pid,sid);o=get(db,TraceOrder,pid,s.order_id);t=get(db,TraceTemplate,pid,s.template_id);v=get(db,Version,pid,o.version_id)
   result=svc.view(db,s,m.roles,history=False)
   return result|dict(has_shipment=bool(db.scalar(select(TraceRecord.id).where(TraceRecord.spool_id==sid,TraceRecord.kind=='shipment').limit(1))),record_total=count(db,TraceRecord,pid,sid),event_total=count(db,TraceEvent,pid,sid),file_total=count(db,TraceFile,pid,sid),weld_total=count(db,TraceWeld,pid,sid),orders=[order_view(o)],templates=[template_view(db,t)],source_document_id=v.document_id,source_version_id=v.id)
 @router.get('/workspace/spools/{sid}/history',response_model=History)
 def history(pid:str,sid:str,kind:Literal['records','events','files','welds'],revision:int=Query(...,ge=1),page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=50),dataset_token:str|None=None,a=Depends(actor)):
  with store.transaction() as db:
   _,m=store.membership(db,a,pid);s=get(db,Spool,pid,sid)
   if s.revision!=revision:fail(409,'REVISION_CONFLICT','管段已更新，请刷新详情后重新核对',current_revision=s.revision)
   cls={'records':TraceRecord,'events':TraceEvent,'files':TraceFile,'welds':TraceWeld}[kind];q=select(cls).where(cls.project_id==pid,cls.spool_id==sid);total=db.scalar(select(func.count()).select_from(q.subquery()));last=db.scalar(select(func.max(cls.id)).where(cls.project_id==pid,cls.spool_id==sid));token=hashlib.sha256(json.dumps([sid,kind,s.revision,total,last]).encode()).hexdigest()
   if page>1 and not dataset_token:fail(422,'PAGE_TOKEN_REQUIRED','请先读取首页，再按同一集合翻页')
   if dataset_token and dataset_token!=token:fail(409,'HISTORY_CHANGED','记录或原件集合已变化，请刷新详情后重新读取')
   ordering=(cls.received_at.desc(),cls.id) if kind=='records' else (cls.at.desc(),cls.id) if kind=='events' else (cls.id,)
   rows=list(db.scalars(q.order_by(*ordering).offset((page-1)*page_size).limit(page_size)));items=[]
   for r in rows:
    if kind=='records':
     data=dict(r.data)
     if not set(m.roles)&{'工厂','现场','质量','项目经理'}:data.pop('welder_code',None)
     files=list(db.scalars(select(TraceFile).where(TraceFile.project_id==pid,TraceFile.spool_id==sid,TraceFile.id.in_(r.file_ids)))) if r.file_ids else []
     items.append({k:getattr(r,k) for k in ['id','kind','file_ids','source','occurred_at','received_at','actor_id','corrects_id']}|dict(data=data,attachments=[file_view(f) for f in files]))
    elif kind=='events':items.append({k:getattr(r,k) for k in ['id','action','body','actor_id','at']})
    elif kind=='files':items.append(file_view(r))
    else:items.append(dict(id=r.id,code=r.code))
   return dict(kind=kind,items=items,total=total,page=page,page_size=page_size,revision=s.revision,dataset_token=token)
 @router.get('/workspace/metrics',response_model=Metrics)
 def metrics(pid:str,a=Depends(actor)):
  with store.transaction() as db:
   _,m=store.membership(db,a,pid);views=[svc.view(db,s,m.roles,history=False) for s in db.scalars(select(Spool).where(Spool.project_id==pid))];return svc.metrics(views)|dict(checked_at=utcnow())
 @router.get('/workspace/choices',response_model=Choices)
 def choices(pid:str,kind:Literal['sources','orders','templates','parents'],page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=50),order_id:str|None=None,template_id:str|None=None,a=Depends(actor)):
  with store.transaction() as db:
   _,m=store.membership(db,a,pid)
   if order_id:o=get(db,TraceOrder,pid,order_id)
   if template_id:get(db,TraceTemplate,pid,template_id)
   if kind=='sources':
    from .change_service import can_start
    q=select(Version,func.json_extract(Version.body,'$.title')).join(Document,Document.id==Version.document_id).where(Document.project_id==pid,Document.kind=='scheme',Version.number==Document.version_no).options(defer(Version.body));items=[]
    for v,title in db.execute(q):
     if source_current(db,v):items.append(dict(id=v.id,label=str(title)+' · v'+str(v.number),available=can_start(db,pid,v)))
    return dict(items=items[(page-1)*page_size:page*page_size],total=len(items),page=page,page_size=page_size)
   if kind=='orders':
    q=select(TraceOrder).where(TraceOrder.project_id==pid,TraceOrder.factory_id==a.id)
    total=db.scalar(select(func.count()).select_from(q.subquery()));rows=db.scalars(q.order_by(TraceOrder.created_at.desc(),TraceOrder.id).offset((page-1)*page_size).limit(page_size));items=[dict(id=o.id,label=o.code,quality_id=o.quality_id) for o in rows]
   elif kind=='templates':
    q=select(TraceTemplate).where(TraceTemplate.project_id==pid)
    if order_id:q=q.where(TraceTemplate.approved_by==o.quality_id)
    total=db.scalar(select(func.count()).select_from(q.subquery()));rows=db.scalars(q.order_by(TraceTemplate.approved_at.desc(),TraceTemplate.id).offset((page-1)*page_size).limit(page_size));items=[dict(id=t.id,label=t.name+' · 焊接'+('适用' if t.welding else '不适用')+' / 试压'+('适用' if t.pressure else '不适用')) for t in rows]
   else:
    if not order_id or not template_id:fail(422,'PARENT_SCOPE','先指定同一订单和模板')
    q=select(Spool).where(Spool.project_id==pid,Spool.order_id==order_id,Spool.template_id==template_id,Spool.state.in_(['registered','fabricating','rework']))
    total=db.scalar(select(func.count()).select_from(q.subquery()));rows=db.scalars(q.order_by(Spool.code,Spool.id).offset((page-1)*page_size).limit(page_size));items=[dict(id=s.id,label=s.code,revision=s.revision,order_id=s.order_id,template_id=s.template_id) for s in rows]
   return dict(items=items,total=total,page=page,page_size=page_size)
 return router
