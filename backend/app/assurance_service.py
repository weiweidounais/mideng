import hashlib,json
from pathlib import Path
from datetime import datetime,timedelta,timezone
from sqlalchemy import select,update
from .pilot_models import Account,Project,Membership,utcnow
from .pilot_service import uid,fail
from .handoff_service import get,cas,effective_member,notify,file_view
from .assurance_models import DataContract,ExceptionCase,ExceptionEvent,ExceptionFile,EvidenceExport

def managed(roles,case):return '财务' in roles if case.financial else '项目经理' in roles

def allowed(roles,a,case):return ('财务' in roles) if case.financial else ('项目经理' in roles or case.owner_id==a.id)

def access(store,db,a,pid,eid):
 _,m=store.membership(db,a,pid);e=get(db,ExceptionCase,pid,eid)
 if not allowed(m.roles,a,e):fail(404,'NOT_ACCESSIBLE','异常不存在或无访问权限')
 return e,m.roles

def record(db,e,action,actor=None,body=None):db.add(ExceptionEvent(id=uid(),project_id=e.project_id,exception_id=e.id,actor_id=actor.id if actor else None,action=action,body=body or {}))

def candidates(db,pid):
 from .handoff_models import Document,Version,Contract,MaterialRow
 from .handoff_service import issue_candidates,latest
 from .procurement_models import PurchaseOrder
 from .change_models import ChangeCase,ChangeVersion,ChangeDisposition
 from .change_service import receipts
 from .trace_models import Spool,TraceOrder
 from .trace_service import view,owner
 from .cost_models import CostBatch,CostClose
 from .cost_service import calculate
 now=utcnow();result=[]
 def add(oid,version,kind,rule,who,title,due=None,financial=False):result.append(dict(object_id=oid,source_version=version or 'draft',source_kind=kind,rule_id=rule,owner_id=who,title=title,due_at=due,financial=int(financial)))
 for oid,rule,who,title in issue_candidates(db,pid):
  d=db.get(Document,oid);c=db.get(Contract,oid);r=db.get(MaterialRow,oid);o=db.get(PurchaseOrder,oid);ch=db.get(ChangeCase,oid)
  version=(latest(db,d).id if d and d.version_no else None) or (c.version_id if c else None) or (db.get(Contract,r.contract_id).version_id if r else None) or (o.version_id if o else None) or (ch.current_version_id if ch else None)
  if ':r' in rule:rule=rule.split(':r')[0]
  if ':v' in rule:rule=rule.split(':v')[0]
  kind='document' if d else 'procurement' if o else 'change' if ch else 'contract'
  due=o.due_at if o else c.due_at if c else (d.draft.get('brief_due_at') if d else None)
  add(oid,version,kind,'bom.'+rule,who,title,due)
 for c in db.scalars(select(ChangeCase).where(ChangeCase.project_id==pid,ChangeCase.current_version_id.is_not(None))):
  if c.state in {'closed','cancelled'}:continue
  v=db.get(ChangeVersion,c.current_version_id);due=(datetime.fromisoformat(v.published_at)+timedelta(hours=4)).isoformat()
  if due>now:continue
  for r in receipts(db,v):
   if not r['delivered_at']:add(c.id,v.id,'change','change.delivery:'+r['account_id'],r['account_id'],'变更发布后4小时仍未有效送达',due)
   if not r['confirmed_at']:add(c.id,v.id,'change','change.ack:'+r['account_id'],r['account_id'],'变更发布后4小时仍未本人确认',due)
  dispositions={d.target_key:d for d in db.scalars(select(ChangeDisposition).where(ChangeDisposition.version_id==v.id))}
  for target in v.body.get('targets',[]):
   d=dispositions.get(target['key'])
   if not d or not d.verified_at:add(c.id,v.id,'change','change.disposition:'+target['key'],d.executor_id if d else c.created_by,'变更旧对象处置尚未核对',due)
 for s in db.scalars(select(Spool).where(Spool.project_id==pid)):
  if s.state in {'registered','scrapped','retired'}:continue
  o=db.get(TraceOrder,s.order_id);v=view(db,s,['项目经理'])
  if not v['source_ok']:add(s.id,o.version_id,'spool','trace.source',o.pm_id,'管段当前来源需复核')
  if s.state in {'inspection','ready','shipped','installed','tested','completed'} and v['missing']:add(s.id,o.version_id,'spool','trace.missing',owner(db,s),'管段到达核对阶段，适用履历/原件仍缺项')
  if s.state in {'rework','hold'}:add(s.id,o.version_id,'spool','trace.nonconformance',owner(db,s),'管段质量不合格，待返修复检')
 for b in db.scalars(select(CostBatch).where(CostBatch.project_id==pid,CostBatch.state=='invalid')):add(b.id,b.profile_id,'cost_batch','cost.precheck',b.actor_id,'成本源批次预检未通过，整批未入账',financial=True)
 for c in db.scalars(select(CostClose).where(CostClose.project_id==pid,CostClose.state.in_(['draft','review']))):
  body=calculate(db,pid,c.inputs)
  if body['gaps']:add(c.id,c.id,'cost_close','cost.reconcile',c.actor_id,'财务月结仍有未补缺项或核对不平',body['deadline'],True)
  if body['deadline'] and body['deadline']<now:add(c.id,c.id,'cost_close','cost.overdue',c.actor_id,'财务月结已超过公司日历截止',body['deadline'],True)
 return result

def reconcile(db,pid=None):
 for project_id in ([pid] if pid else list(db.scalars(select(Project.id)))):
  current=candidates(db,project_id);existing={(e.object_id,e.source_version,e.rule_id):e for e in db.scalars(select(ExceptionCase).where(ExceptionCase.project_id==project_id))};active=set()
  for value in current:
   k=(value['object_id'],value['source_version'],value['rule_id']);active.add(k);e=existing.get(k)
   if not e:
    e=ExceptionCase(id=uid(),project_id=project_id,**value);db.add(e);db.flush();record(db,e,'detected');notify(db,project_id,[e.owner_id],'业务异常待核对：'+e.title,'assurance',e.id,e.source_version)
   elif e.state=='resolved':e.state='open';e.revision+=1;e.resolved_at=None;e.waiver_until=None;e.waiver={};record(db,e,'reopened')
   elif e.state=='waived' and (not e.waiver_until or e.waiver_until<=utcnow()):e.state='open';e.revision+=1;record(db,e,'waiver.expired')
  for k,e in existing.items():
   if k not in active and e.state!='resolved':e.state='resolved';e.resolved_at=utcnow();e.revision+=1;record(db,e,'fact.resolved')

def original(f):
 p=Path(f.path)
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=f.sha256:fail(409,'EVIDENCE_INTEGRITY','证据原件缺失或哈希不符')
 return p.read_bytes()

def case_view(db,e,roles):return {k:getattr(e,k) for k in ['id','object_id','source_version','source_kind','rule_id','rule_version','owner_id','title','financial','state','revision','detected_at','due_at','resolved_at','waiver_until','waiver']}|{'can_manage':managed(roles,e),'events':[dict(action=v.action,actor_id=v.actor_id,at=v.at,body=v.body) for v in db.scalars(select(ExceptionEvent).where(ExceptionEvent.exception_id==e.id).order_by(ExceptionEvent.at))],'files':[file_view(f) for f in db.scalars(select(ExceptionFile).where(ExceptionFile.exception_id==e.id))]}

def contracts(db):return [dict(id=x.id,name=x.name,version=x.version,body=x.body,effective_at=x.effective_at) for x in db.scalars(select(DataContract).order_by(DataContract.id))]
def export_view(e):return {k:getattr(e,k) for k in ['id','state','revision','include_sensitive','error','at','completed_at','sha256']}
def board(store,db,a,pid):
 _,m=store.membership(db,a,pid)
 return dict(exceptions=[case_view(db,e,m.roles) for e in db.scalars(select(ExceptionCase).where(ExceptionCase.project_id==pid).order_by(ExceptionCase.detected_at.desc())) if allowed(m.roles,a,e)],exports=[export_view(x) for x in db.scalars(select(EvidenceExport).where(EvidenceExport.project_id==pid,EvidenceExport.actor_id==a.id).order_by(EvidenceExport.at.desc()))],contracts=contracts(db))

def act(store,db,a,e,roles,b,rid):
 if b.action in {'assign','waive'} and not managed(roles,e):fail(403,'EXCEPTION_MANAGER','指派/豁免须项目经理（财务异常须财务）')
 values={}
 if b.action=='assign':
  if not b.owner_id or not b.reason or not effective_member(db,e.project_id,b.owner_id,{'财务'} if e.financial else None):fail(422,'OWNER_REQUIRED','须选择有效项目责任账号并填写指派依据')
  values={'owner_id':b.owner_id};notify(db,e.project_id,[b.owner_id],'业务异常已指派：'+e.title,'assurance',e.id,e.source_version)
 elif b.action=='waive':
  if e.state=='resolved' or not b.reason or not b.approval_no or not b.file_ids or not b.until or not datetime.now(timezone.utc)<b.until<=datetime.now(timezone.utc)+timedelta(days=30):fail(422,'WAIVER_REQUIRED','豁免须未修复事实、原因、既有批准编号/原件和未来30天内期限')
  for fid in b.file_ids:
   f=get(db,ExceptionFile,e.project_id,fid)
   if f.exception_id!=e.id:fail(422,'EVIDENCE_SCOPE','豁免依据须属于本异常')
   original(f)
  values={'state':'waived','waiver_until':b.until.isoformat(),'waiver':{'reason':b.reason,'approval_no':b.approval_no,'file_ids':b.file_ids,'actor_id':a.id}}
 elif b.action=='remind':
  recent=db.scalar(select(ExceptionEvent).where(ExceptionEvent.exception_id==e.id,ExceptionEvent.action=='remind').order_by(ExceptionEvent.at.desc()))
  if recent and recent.at>(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat():fail(409,'REMIND_COOLDOWN','一分钟内已有催办，不重复通知')
  notify(db,e.project_id,[e.owner_id],'业务异常催办：'+e.title,'assurance',e.id,e.source_version)
 result=db.execute(update(ExceptionCase).where(ExceptionCase.id==e.id,ExceptionCase.revision==b.revision).values(revision=ExceptionCase.revision+1,**values))
 if result.rowcount!=1:fail(409,'REVISION_CONFLICT','异常版本已变化，请保留输入并读取最新状态',current_revision=e.revision)
 db.refresh(e);record(db,e,b.action,a,b.model_dump(mode='json',exclude={'revision','action'}));store.audit(db,a,'assurance.'+b.action,e.id,e.revision,rid,e.project_id);return {'id':e.id,'revision':e.revision}
