"""Compatible, role-filtered projections for financial forms and bounded row review."""
import json
from typing import Any,Literal
from fastapi import APIRouter,Depends,Query
from pydantic import BaseModel
from sqlalchemy import select,func,true,Integer
from sqlalchemy.orm import defer
from . import cost_service as svc
from .cost_models import CostBatch,CostClose,CostSnapshot,CostProfile,CostCalendar,CostBudget,CostSource
from .cost_schemas import BoardOut,BatchOut
from .handoff_service import get,file_view
from .pilot_service import fail

class BatchSummary(BatchOut):
 rows_count:int;errors_count:int;normalized_count:int
class Workspace(BoardOut):
 batches:list[BatchSummary]
 batch_total:int;close_total:int;snapshot_total:int
class Rows(BaseModel):
 kind:Literal['rows','errors','normalized'];revision:int;page:int;page_size:int;total:int;validation_error_total:int;items:list[dict[str,Any]]
class Replacement(BaseModel):id:str;profile_id:str;source_id:str;source_name:str;meta:dict
class Replacements(BaseModel):items:list[Replacement];total:int;page:int;page_size:int

def batch_query(pid):
 return select(CostBatch,func.json_array_length(CostBatch.rows),func.json_array_length(CostBatch.errors),func.json_array_length(CostBatch.normalized)).where(CostBatch.project_id==pid).options(defer(CostBatch.rows),defer(CostBatch.errors),defer(CostBatch.normalized))
def summary(row):
 b,rows,errors,normalized=row
 value={k:getattr(b,k) for k in BatchOut.model_fields if k not in {'rows','errors','normalized'}}
 return value|dict(rows=[],errors=[],normalized=[],rows_count=rows,errors_count=errors,normalized_count=normalized)

def make_cost_workspace(store,actor):
 router=APIRouter(prefix='/projects/{pid}/cost',tags=['财务表单核对'])
 @router.get('/workspace',response_model=Workspace)
 def workspace(pid:str,batch_page:int=Query(1,ge=1),close_page:int=Query(1,ge=1),snapshot_page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=50),object_id:str|None=None,kind:Literal['cost_batch','cost_close','cost_snapshot']|None=None,a=Depends(actor)):
  with store.transaction() as db:
   _,member=store.membership(db,a,pid);fin='财务' in member.roles;public=fin or '项目经理' in member.roles
   result=dict(can_finance=fin,can_summary=public,profiles=[],calendars=[],budgets=[],files=[],batches=[],closes=[],snapshots=[],changes=[],batch_total=0,close_total=0,snapshot_total=0)
   if bool(object_id)!=bool(kind):fail(422,'LOCATION_INVALID','须同时指定成本对象与类型')
   if object_id:
    if kind in {'cost_batch','cost_close'} and not fin:fail(404,'NOT_ACCESSIBLE','当前岗位不可读财务源对象')
    if kind=='cost_snapshot' and not public:fail(404,'NOT_ACCESSIBLE','当前岗位不可读发布汇总')
    cls={'cost_batch':CostBatch,'cost_close':CostClose,'cost_snapshot':CostSnapshot}[kind]
    if not db.scalar(select(cls.id).where(cls.project_id==pid,cls.id==object_id)):fail(404,'NOT_ACCESSIBLE','成本对象不存在或无读取权限')
   def page(cls,n,target_kind):
    q=select(cls).where(cls.project_id==pid);total=db.scalar(select(func.count()).select_from(q.subquery()))
    if object_id and kind==target_kind:q=q.where(cls.id==object_id)
    else:q=q.order_by(cls.at.desc(),cls.id).offset((n-1)*page_size).limit(page_size)
    return list(db.scalars(q)),total
   if fin:
    result['profiles']=[dict(id=p.id,number=p.number,body=p.body) for p in db.scalars(select(CostProfile).where(CostProfile.project_id==pid))]
    result['calendars']=[dict(id=p.id,body=p.body) for p in db.scalars(select(CostCalendar).where(CostCalendar.project_id==pid))]
    result['budgets']=[dict(id=p.id,body=p.body) for p in db.scalars(select(CostBudget).where(CostBudget.project_id==pid))]
    result['files']=[file_view(f) for f in db.scalars(select(CostSource).where(CostSource.project_id==pid))]
    q=batch_query(pid);result['batch_total']=db.scalar(select(func.count()).select_from(CostBatch).where(CostBatch.project_id==pid))
    q=q.where(CostBatch.id==object_id) if kind=='cost_batch' else q.order_by(CostBatch.at.desc(),CostBatch.id).offset((batch_page-1)*page_size).limit(page_size)
    result['batches']=[summary(row) for row in db.execute(q)]
    rows,result['close_total']=page(CostClose,close_page,'cost_close');result['closes']=[dict(id=c.id,revision=c.revision,state=c.state,inputs=c.inputs,body=c.body,publication_id=c.publication_id) for c in rows]
    from .change_models import ChangeCase
    result['changes']=[dict(id=c.id,title=c.draft['title']) for c in db.scalars(select(ChangeCase).where(ChangeCase.project_id==pid,ChangeCase.current_version_id.is_not(None),ChangeCase.state!='cancelled'))]
   if public:
    rows,result['snapshot_total']=page(CostSnapshot,snapshot_page,'cost_snapshot')
    for s in rows:
     latest=svc.latest_snapshot(db,pid,{'period':s.period,'currency':s.currency,'tax_basis':s.tax_basis});body=s.body if fin else {k:s.body.get(k) for k in svc.PUBLIC};result['snapshots'].append(dict(id=s.id,number=s.number,previous_id=s.previous_id,body=body,actor_id=s.actor_id,at=s.at,is_current=s.id==latest.id))
   return result
 @router.get('/batches/{bid}/review-rows',response_model=Rows)
 def rows(pid:str,bid:str,kind:Literal['rows','errors','normalized'],revision:int=Query(...,ge=1),page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=50),a=Depends(actor)):
  with store.transaction() as db:
   svc.finance(store,db,a,pid)
   b=db.scalar(select(CostBatch).where(CostBatch.project_id==pid,CostBatch.id==bid).options(defer(CostBatch.rows),defer(CostBatch.errors),defer(CostBatch.normalized)))
   if not b:fail(404,'NOT_ACCESSIBLE','批次不存在或无读取权限')
   if b.revision!=revision:fail(409,'REVISION_CONFLICT','批次已更新，请刷新批次后重新核对',current_revision=b.revision)
   column=getattr(CostBatch,kind);total=db.scalar(select(func.json_array_length(column)).where(CostBatch.id==bid));each=func.json_each(column).table_valued('key','value')
   values=db.scalars(select(each.c.value).select_from(CostBatch).join(each,true()).where(CostBatch.id==bid,CostBatch.project_id==pid).order_by(each.c.key.cast(Integer)).offset((page-1)*page_size).limit(page_size))
   return dict(kind=kind,revision=b.revision,page=page,page_size=page_size,total=total,validation_error_total=b.differences.get('error_count',total if kind=='errors' else 0),items=[json.loads(v) for v in values])
 @router.get('/replacement-options',response_model=Replacements)
 def replacements(pid:str,profile_id:str,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=50),a=Depends(actor)):
  with store.transaction() as db:
   svc.finance(store,db,a,pid);profile=get(db,CostProfile,pid,profile_id)
   q=select(CostBatch.id,CostBatch.profile_id,CostBatch.source_id,CostBatch.meta,CostSource.name).join(CostProfile,CostBatch.profile_id==CostProfile.id).join(CostSource,CostBatch.source_id==CostSource.id).where(CostBatch.project_id==pid,CostBatch.state=='committed',CostProfile.source_system==profile.source_system)
   total=db.scalar(select(func.count()).select_from(q.subquery()));rows=db.execute(q.order_by(CostBatch.at.desc(),CostBatch.id).offset((page-1)*page_size).limit(page_size))
   return dict(items=[dict(id=r.id,profile_id=r.profile_id,source_id=r.source_id,source_name=r.name,meta=r.meta) for r in rows],total=total,page=page,page_size=page_size)
 return router
