from .pilot_service import business_roles
"""Additive, read-only navigation and bounded workspace projections."""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from fastapi import APIRouter,Depends,Query,HTTPException
from pydantic import BaseModel
from sqlalchemy import select,func,or_
from .pilot_models import Todo,Membership,Project,utcnow
from .pilot_service import fail
from . import handoff_service as hs
from .handoff_models import Document,Version,Contract,MaterialRow
from .handoff_schemas import BoardOut,DocOut
from .procurement_models import PurchaseOrder
from .procurement_schemas import ProcurementOut
from .workbench_knowledge import Question,Answer,answer_question
Section=Literal['requirements','procurement','changes','trace','cost','assurance','knowledge']
class Link(BaseModel):
 project_id:str;section:Section;object_id:str|None=None;version_id:str|None=None;kind:str|None=None;title:str='';state:str='';owner_id:str|None=None;due_at:str|None=None
class Task(BaseModel):id:str;title:str;project_name:str;created_at:str;pending:bool;link:Link
class Tasks(BaseModel):items:list[Task];total:int;page:int;page_size:int;pending_total:int
class DocItem(BaseModel):id:str;kind:str;parent_id:str|None;title:str;version_no:int;has_draft:bool
class Docs(BaseModel):items:list[DocItem];total:int;page:int;page_size:int
class PurchaseItem(BaseModel):id:str;title:str;state:str;version_id:str;owner_id:str;due_at:str
class Purchases(BaseModel):items:list[PurchaseItem];total:int;page:int;page_size:int
class BomOption(BaseModel):id:str;document_id:str;title:str;number:int;can_request:bool
class Boms(BaseModel):items:list[BomOption];total:int;page:int;page_size:int
class Comparison(BaseModel):line_no:int;material:str;spec:str;required_quantity:str;ordered_quantity:str|None;unit:str;need_by:str;eta:str|None;quantity_changed:bool;late_eta:bool
class PurchaseDetail(BaseModel):order:ProcurementOut;source:Link;source_number:int;source_title:str;source_current:bool;comparison:list[Comparison]

def locate(store,db,a,pid,section,oid=None,version=None,kind=None):
 _,m=store.membership(db,a,pid);roles=business_roles(m.roles)
 allowed={'requirements':{'document'},'procurement':{'procurement','contract'},'changes':{'change'},'trace':{'spool','trace_order'},'cost':{'cost_batch','cost_close','cost_snapshot'},'assurance':{'assurance'},'knowledge':{'library'}}
 if kind and kind not in allowed[section]:fail(422,'LOCATION_INVALID','对象类型与板块不匹配')
 if not oid:
  if version:fail(422,'LOCATION_INVALID','来源版本须连同对应对象打开')
  return dict(project_id=pid,section=section,object_id=None,version_id=None,kind=None,title='',state='',owner_id=None,due_at=None)
 title='';state='';owner=None;due=None;resolved_version=version
 def require_version(expected):
  if version and version!=expected:fail(404,'NOT_ACCESSIBLE','该版本不属于当前对象')
 if section=='knowledge':
  if version:fail(422,'LOCATION_INVALID','知识空间不接受业务正式版本参数')
  from .knowledge_api import visible
  l=visible(store,db,a,pid,oid);title=l.name;state='current';kind='library';owner=l.owner_id
 elif section=='requirements':
  d=hs.get(db,Document,pid,oid)
  if not hs.visible(db,d,a,roles):fail(404,'NOT_ACCESSIBLE','来源不存在或无读取权限')
  v=hs.get(db,Version,pid,version) if version else hs.latest(db,d)
  if v and v.document_id!=d.id:fail(404,'NOT_ACCESSIBLE','该正式版本不属于当前文档')
  title=(v.body if v else d.draft).get('title','需求与方案');state='current' if v and hs.source_current(db,v) and v.number==d.version_no else 'historical' if v else 'draft';resolved_version=v.id if v else None;kind='document';owner=d.created_by
 elif section=='procurement':
  if kind=='contract':
   c=hs.get(db,Contract,pid,oid)
   if c.state=='draft' and c.created_by!=a.id and not set(roles)&{'设计','采购'}:fail(404,'NOT_ACCESSIBLE','历史交接不可读')
   require_version(c.version_id);resolved_version=c.version_id;title=c.deliverable;state=c.state;owner=c.recipient_id;due=c.due_at
  else:
   from .procurement_service import owner as purchase_owner
   o=hs.get(db,PurchaseOrder,pid,oid);require_version(o.version_id);resolved_version=o.version_id;title=o.title;state=o.state;owner=purchase_owner(o);due=o.due_at;kind='procurement'
 elif section=='changes':
  from .change_models import ChangeCase,ChangeVersion
  c=hs.get(db,ChangeCase,pid,oid);v=hs.get(db,ChangeVersion,pid,version) if version else (db.get(ChangeVersion,c.current_version_id) if c.current_version_id else None)
  if v and v.case_id!=c.id:fail(404,'NOT_ACCESSIBLE','变更版本不属于该对象')
  if not v and c.created_by!=a.id and not set(roles)&{'项目经理','设计','商务','质量','财务'}:fail(404,'NOT_ACCESSIBLE','变更草稿不可读')
  title=(v.body if v else c.draft).get('title','变更');state=c.state;owner=c.created_by;resolved_version=v.id if v else None;kind='change'
 elif section=='trace':
  from .trace_models import Spool,TraceOrder
  from .trace_service import owner as spool_owner
  if kind=='trace_order':o=hs.get(db,TraceOrder,pid,oid);title=o.code;owner=o.factory_id
  else:s=hs.get(db,Spool,pid,oid);o=hs.get(db,TraceOrder,pid,s.order_id);title=s.code;owner=spool_owner(db,s);state=s.state;kind='spool'
  require_version(o.version_id);resolved_version=o.version_id
 elif section=='cost':
  from .cost_models import CostBatch,CostClose,CostSnapshot
  if kind=='cost_snapshot':
   if not set(roles)&{'项目经理','财务'}:fail(404,'NOT_ACCESSIBLE','当前岗位不可读财务发布汇总')
   o=hs.get(db,CostSnapshot,pid,oid);title=o.period+' 已发布月结';state='published';owner=o.actor_id;require_version(o.id);resolved_version=o.id
  else:
   if '财务' not in roles:fail(404,'NOT_ACCESSIBLE','当前岗位不可读财务源数据')
   cls=CostClose if kind=='cost_close' else CostBatch;o=hs.get(db,cls,pid,oid);title='财务月结核对' if cls==CostClose else '财务成本批次';state=o.state;owner=o.actor_id;expected=o.id if cls==CostClose else o.profile_id;require_version(expected);resolved_version=expected;kind='cost_close' if cls==CostClose else 'cost_batch'
 else:
  from .assurance_service import access
  o,_=access(store,db,a,pid,oid);title=o.title;state=o.state;owner=o.owner_id;due=o.due_at;require_version(o.source_version);resolved_version=o.source_version;kind='assurance'
 return dict(project_id=pid,section=section,object_id=oid,version_id=resolved_version,kind=kind,title=title,state=state,owner_id=owner,due_at=due)

def can_request(db,v,a):
 from .procurement_service import effective_member
 recipients=[x for x in v.recipients if effective_member(db,v.project_id,x,{'项目经理'})]
 member=db.scalar(select(Membership).where(Membership.project_id==v.project_id,Membership.account_id==a.id))
 return not recipients or a.id in recipients or bool(member and '管理员' in member.roles and effective_member(db,v.project_id,a.id))

def actionable(db,a,roles,link):
 roles=business_roles(roles);kind=link['kind'];oid=link['object_id'];state=link['state'];owner=link['owner_id']
 if not oid:return False
 if kind=='document':
  d=db.get(Document,oid);v=db.get(Version,link['version_id']) if link['version_id'] else None
  if not v or v.number!=d.version_no or not hs.source_current(db,v):return False
  if d.kind=='scheme':return '项目经理' in roles and can_request(db,v,a) and not db.scalar(select(PurchaseOrder.id).where(PurchaseOrder.version_id==v.id))
  if '设计' not in roles or a.id not in v.recipients:return False
  schemes=list(db.scalars(select(Document).where(Document.parent_id==d.id,Document.version_no>0)))
  return not any(hs.source_current(db,hs.latest(db,s)) for s in schemes)
 if kind=='procurement':
  o=db.get(PurchaseOrder,oid);role={'requested':'采购','purchasing':'采购','request_returned':'项目经理','pm_review':'项目经理','quality_wait':'质量','quality_check':'质量','quality_rework':'采购','business_archive':'商务'}.get(state)
  return owner==a.id and state!='archived' and role in roles
 if kind=='change':
  from .change_models import ChangeCase,ChangeAck,ChangeDisposition
  c=db.get(ChangeCase,oid)
  if state in {'closed','cancelled'} or c.current_version_id!=link['version_id']:return False
  return not db.scalar(select(ChangeAck.id).where(ChangeAck.version_id==c.current_version_id,ChangeAck.actor_id==a.id)) or bool(db.scalar(select(ChangeDisposition.id).where(ChangeDisposition.version_id==c.current_version_id,ChangeDisposition.executor_id==a.id,ChangeDisposition.verified_at.is_(None))))
 if kind=='spool':return owner==a.id and state not in {'completed','scrapped','retired'} and bool(set(roles)&{'工厂','现场','质量','项目经理'})
 if kind=='trace_order':
  from .trace_models import Spool
  return owner==a.id and '工厂' in roles and not db.scalar(select(Spool.id).where(Spool.order_id==oid))
 if kind=='cost_batch':return '财务' in roles and owner==a.id and state not in {'committed','withdrawn','replaced'}
 if kind=='cost_close':return '财务' in roles and owner==a.id and state in {'draft','review'}
 if kind=='assurance':return state!='resolved' and owner==a.id
 if kind=='contract':return state not in {'closed','cancelled'} and (owner==a.id or db.get(Contract,oid).created_by==a.id)
 return False

def make_workspace_router(store,actor):
 router=APIRouter(tags=['工作台与导航'])
 @router.post('/projects/{pid}/workspace/ask',response_model=Answer)
 def ask(pid:str,b:Question,a=Depends(actor)):
  with store.transaction() as db:return answer_question(store,db,a,pid,b)
 @router.get('/workbench',response_model=Tasks)
 def workbench(project_id:str|None=None,mode:Literal['pending','all']='pending',page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=50),a=Depends(actor)):
  with store.transaction() as db:
   memberships={m.project_id:m for m in db.scalars(select(Membership).where(Membership.account_id==a.id,Membership.active.is_(True),Membership.valid_from<=utcnow(),or_(Membership.valid_until.is_(None),Membership.valid_until>utcnow())))}
   if project_id:store.membership(db,a,project_id)
   items=[];seen=set();cache={};pending_total=0
   for t in db.scalars(select(Todo).where(Todo.recipient_id==a.id).order_by(Todo.created_at.desc(),Todo.id.desc())):
    if t.project_id not in memberships or (project_id and t.project_id!=project_id):continue
    section={'document':'requirements','contract':'procurement','procurement':'procurement','change':'changes','spool':'trace','trace_order':'trace','assurance':'assurance'}.get(t.target_kind,'cost' if (t.target_kind or '').startswith('cost_') else None)
    k=(t.project_id,t.target_kind,t.target_id,t.version_id)
    if k in seen:continue
    try:
     if k not in cache:cache[k]=locate(store,db,a,t.project_id,section or 'requirements',t.target_id if section else None,t.version_id if section else None,t.target_kind)
     link=cache[k];is_pending=actionable(db,a,memberships[t.project_id].roles,link)
    except HTTPException as err:
     if err.status_code in {403,404}:continue
     raise
    seen.add(k);pending_total+=int(is_pending)
    if mode=='pending' and not is_pending:continue
    project=db.get(Project,t.project_id);items.append(dict(id=t.id,title=link['title'] or t.title,project_name=project.name,created_at=t.created_at,pending=is_pending,link=link))
   return dict(items=items[(page-1)*page_size:page*page_size],total=len(items),page=page,page_size=page_size,pending_total=pending_total)
 @router.get('/projects/{pid}/workspace/locate',response_model=Link)
 def location(pid:str,section:Section,object_id:str|None=None,version_id:str|None=None,kind:str|None=None,a=Depends(actor)):
  with store.transaction() as db:return locate(store,db,a,pid,section,object_id,version_id,kind)
 def visible_query(pid,a,roles):
  q=select(Document).where(Document.project_id==pid)
  if not set(roles)&{'市场','商务','设计'}:q=q.where(or_(Document.version_no>0,Document.created_by==a.id))
  elif set(roles)&{'市场','商务'} and '设计' not in roles:q=q.where(or_(Document.kind=='requirement',Document.version_no>0,Document.created_by==a.id))
  elif '设计' in roles and not set(roles)&{'市场','商务'}:q=q.where(or_(Document.kind=='scheme',Document.version_no>0,Document.created_by==a.id))
  return q
 @router.get('/projects/{pid}/workspace/documents',response_model=Docs)
 def documents(pid:str,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=50),a=Depends(actor)):
  with store.transaction() as db:
   _,m=store.membership(db,a,pid);q=visible_query(pid,a,business_roles(m.roles)).where(Document.kind=='requirement');total=db.scalar(select(func.count()).select_from(q.subquery()));rows=db.scalars(q.order_by(Document.created_at.desc(),Document.id).offset((page-1)*page_size).limit(page_size));items=[]
   for d in rows:
    v=hs.latest(db,d);can_draft=d.created_by==a.id or bool(set(business_roles(m.roles))&hs.EDIT[d.kind]);body=d.draft if d.has_draft and can_draft else (v.body if v else {});items.append(dict(id=d.id,kind=d.kind,parent_id=d.parent_id,title=body.get('title','需求'),version_no=d.version_no,has_draft=d.has_draft))
   return dict(items=items,total=total,page=page,page_size=page_size)
 @router.get('/projects/{pid}/workspace/document-context/{did}',response_model=BoardOut)
 def document_context(pid:str,did:str,version_id:str|None=None,a=Depends(actor)):
  with store.transaction() as db:
   _,m=store.membership(db,a,pid);locate(store,db,a,pid,'requirements',did,version_id,'document');d=hs.get(db,Document,pid,did);parent=d.parent_id or d.id;docs=[x for x in db.scalars(select(Document).where(Document.project_id==pid,or_(Document.id==parent,Document.parent_id==parent))) if hs.visible(db,x,a,business_roles(m.roles))]
   return dict(documents=[hs.document_view(db,d,a,business_roles(m.roles)) for d in docs],contracts=[],rows=[],arrivals=[],issues=[],events=[])
 @router.get('/projects/{pid}/workspace/sources',response_model=BoardOut)
 def sources(pid:str,a=Depends(actor)):
  with store.transaction() as db:
   _,m=store.membership(db,a,pid);docs=list(db.scalars(visible_query(pid,a,business_roles(m.roles))))
   return dict(documents=[hs.document_view(db,d,a,business_roles(m.roles)) for d in docs],contracts=[],rows=[],arrivals=[],issues=[],events=[])
 @router.get('/projects/{pid}/workspace/procurement',response_model=Purchases)
 def procurement(pid:str,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=50),a=Depends(actor)):
  from .procurement_service import owner
  with store.transaction() as db:
   store.membership(db,a,pid);q=select(PurchaseOrder).where(PurchaseOrder.project_id==pid);total=db.scalar(select(func.count()).select_from(q.subquery()));rows=db.scalars(q.order_by(PurchaseOrder.created_at.desc(),PurchaseOrder.id).offset((page-1)*page_size).limit(page_size))
   return dict(items=[dict(id=o.id,title=o.title,state=o.state,version_id=o.version_id,owner_id=owner(o),due_at=o.due_at) for o in rows],total=total,page=page,page_size=page_size)
 @router.get('/projects/{pid}/workspace/purchase-orders/{oid}',response_model=PurchaseDetail)
 def purchase(pid:str,oid:str,a=Depends(actor)):
  from .procurement_service import view
  with store.transaction() as db:
   _,m=store.membership(db,a,pid);o=hs.get(db,PurchaseOrder,pid,oid);v=hs.get(db,Version,pid,o.version_id);comparison=[];ordered={r['line_no']:r for r in o.result['lines']} if o.result else {}
   for i,line in enumerate(o.lines,1):
    order=ordered.get(i);comparison.append(dict(line_no=i,material=line['material'],spec=line['spec'],required_quantity=line['quantity'],ordered_quantity=order['quantity'] if order else None,unit=line['unit'],need_by=line['need_by'],eta=order['eta'] if order else None,quantity_changed=bool(order and Decimal(order['quantity'])!=Decimal(line['quantity'])),late_eta=bool(order and order['eta']>line['need_by'])))
   return dict(order=view(db,o,a,business_roles(m.roles)),source=locate(store,db,a,pid,'requirements',v.document_id,v.id,'document'),source_number=v.number,source_title=v.body['title'],source_current=hs.source_current(db,v),comparison=comparison)
 @router.get('/projects/{pid}/workspace/bom-options',response_model=Boms)
 def boms(pid:str,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=50),a=Depends(actor)):
  with store.transaction() as db:
   _,m=store.membership(db,a,pid);items=[]
   for d in db.scalars(select(Document).where(Document.project_id==pid,Document.kind=='scheme',Document.version_no>0)):
    v=hs.latest(db,d)
    if hs.source_current(db,v) and not db.scalar(select(PurchaseOrder.id).where(PurchaseOrder.version_id==v.id)):items.append(dict(id=v.id,document_id=d.id,title=v.body['title'],number=v.number,can_request='项目经理' in business_roles(m.roles) and can_request(db,v,a)))
   return dict(items=items[(page-1)*page_size:page*page_size],total=len(items),page=page,page_size=page_size)
 return router
