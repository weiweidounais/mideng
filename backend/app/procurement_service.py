from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
import hashlib
from sqlalchemy import select
from .pilot_models import utcnow
from .pilot_service import uid,fail
from .handoff_models import Version,Document
from .handoff_service import role,get,effective_member,source_current,cas,notify,file_view
from .procurement_models import PurchaseOrder,PurchaseEvent,PurchaseFile

LABELS={'requested':'待采购接单','request_returned':'采购需求待补正','purchasing':'采购执行中','pm_review':'待项目经理复核','quality_wait':'质量待到货','quality_check':'待质量验收','quality_rework':'质量不合格待整改','business_archive':'待商务归档','archived':'已归档'}

def owner(o):
    if o.state in {'request_returned','pm_review'}:return o.pm_id
    if o.state in {'quality_wait','quality_check'}:return o.quality_id
    if o.state in {'business_archive','archived'}:return o.commerce_id
    return o.purchase_id

def view(db,o,a,roles):
    from .change_service import execution_status,related_change
    related=related_change(db,o.project_id,'procurement',o.id)
    executable,change_status=execution_status(db,o.project_id,'procurement',o.id,get(db,Version,o.project_id,o.version_id))
    money=bool(set(roles)&{'商务','财务'})
    events=[dict(id=e.id,action=e.action,actor_id=e.actor_id,body=e.body,at=e.at) for e in db.scalars(select(PurchaseEvent).where(PurchaseEvent.order_id==o.id).order_by(PurchaseEvent.at))]
    # Unreferenced financial uploads are never advertised in public project reads.
    files=[file_view(f) for f in db.scalars(select(PurchaseFile).where(PurchaseFile.order_id==o.id)) if f.purpose!='archive' or money]
    return {k:getattr(o,k) for k in ['id','project_id','version_id','revision','state','title','note','pm_id','purchase_id','quality_id','commerce_id','lines','result','arrivals','due_at','created_at','updated_at']}|{'owner_id':owner(o),'overdue':o.state!='archived' and o.due_at<utcnow(),'needs_review':not executable,'change_status':change_status,'change_id':related[0].id if related else None, 'archive':o.archive if money else None,'archive_total':str(sum((Decimal(x['amount']) for x in o.archive['costs']),Decimal(0))) if o.archive and money else None,'events':events,'files':files}

def record(store,db,a,o,action,rid,body):
    store.audit(db,a,'procurement.'+action,o.id,o.revision,rid,o.project_id)
    db.add(PurchaseEvent(id=uid(),project_id=o.project_id,order_id=o.id,action=action,actor_id=a.id,body=body))
    notify(db,o.project_id,[owner(o)],LABELS[o.state]+'：'+o.title,'procurement',o.id,o.version_id)

def validate_actors(db,o):
    for aid,r in [(o.pm_id,'项目经理'),(o.purchase_id,'采购'),(o.quality_id,'质量'),(o.commerce_id,'商务')]:
        if not effective_member(db,o.project_id,aid,{r}):fail(422,'INVALID_RECIPIENT','项目经理、采购、质量、商务接收人须为有效项目岗位，请管理员核对授权')

def create(store,db,a,pid,b,rid):
    role(store,db,a,pid,{'项目经理'})
    v=get(db,Version,pid,b.version_id);d=get(db,Document,pid,v.document_id)
    if d.kind!='scheme' or not source_current(db,v):fail(409,'SOURCE_VERSION','须选择当前有效正式方案/BOM')
    from .change_service import can_start
    if not can_start(db,pid,v):fail(409,'CHANGE_NOT_CONFIRMED','新来源的变更批准、必需接收确认或旧对象处置核对未齐，不能创建新采购任务')
    if db.scalar(select(PurchaseOrder.id).where(PurchaseOrder.version_id==v.id)):
        fail(409,'PURCHASE_EXISTS','此正式BOM已建立采购需求，请打开现有采购单')
    pm_recipients=[x for x in v.recipients if effective_member(db,pid,x,{'项目经理'})]
    if pm_recipients and a.id not in pm_recipients:fail(403,'RECIPIENT_ONLY','仅设计指定的项目经理可提交采购需求')
    o=PurchaseOrder(id=uid(),project_id=pid,version_id=v.id,title=b.title,note=b.note,pm_id=a.id,purchase_id=b.purchase_id,quality_id=b.quality_id,commerce_id=b.commerce_id,lines=v.body['bom'],due_at=(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat())
    validate_actors(db,o);db.add(o);db.flush()
    record(store,db,a,o,'request',rid,{'version_id':v.id,'note':b.note});return {'id':o.id,'revision':o.revision}

def files_valid(db,o,ids,purpose):
    if not ids:fail(422,'EVIDENCE_REQUIRED','请上传并选择本采购单的原件证据')
    for fid in ids:
        f=get(db,PurchaseFile,o.project_id,fid)
        if f.order_id!=o.id or f.purpose!=purpose:fail(422,'FILE_SCOPE','附件须属于当前采购单和正确用途')
        path=Path(f.path)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=f.sha256:fail(409,'ORIGINAL_MISSING','附件原件缺失或校验不符，不能确认')

def action(store,db,a,pid,o,b,rid):
    roles=store.membership(db,a,pid)[1].roles
    mapping={
        'accept_purchase':('requested','purchasing','采购',o.purchase_id),
        'return_request':('requested','request_returned','采购',o.purchase_id),
        'resubmit_request':('request_returned','requested','项目经理',o.pm_id),
        'submit_result':('purchasing','pm_review','采购',o.purchase_id),
        'approve_purchase':('pm_review','quality_wait','项目经理',o.pm_id),
        'reject_purchase':('pm_review','purchasing','项目经理',o.pm_id),
        'pass_quality':('quality_check','business_archive','质量',o.quality_id),
        'fail_quality':('quality_check','quality_rework','质量',o.quality_id),
        'rectify':('quality_rework','quality_check','采购',o.purchase_id),
        'archive':('business_archive','archived','商务',o.commerce_id)}
    if b.action=='arrival':
        if not ((a.id==o.purchase_id and '采购' in roles) or (a.id==o.quality_id and '质量' in roles)):fail(403,'RECIPIENT_ONLY','仅指定采购或质量账号可登记到货')
        if o.state not in {'quality_wait','quality_check'}:fail(409,'STATE_CONFLICT','须项目经理复核通过、交质量待到货后登记')
        if not b.arrival:fail(422,'ARRIVAL_REQUIRED','请填写实际到货批次')
        arr=b.arrival.model_dump(mode='json')
        if b.arrival.occurred_at>datetime.now(timezone.utc):fail(422,'FUTURE_ARRIVAL','实际到货时间不能在未来')
        line=next((x for x in o.result['lines'] if x['line_no']==b.arrival.line_no),None)
        if not line:fail(422,'INVALID_LINE','料行不存在')
        total=sum((Decimal(x['quantity']) for x in o.arrivals if x['line_no']==arr['line_no']),Decimal(0))+b.arrival.quantity
        if total>Decimal(line['quantity']):fail(422,'EXCESS_ARRIVAL','分批累计不能超过已复核的订购数量')
        arrivals=[*o.arrivals,arr|{'id':uid(),'actor_id':a.id}]
        complete=all(sum((Decimal(x['quantity']) for x in arrivals if x['line_no']==l['line_no']),Decimal(0))==Decimal(l['quantity']) for l in o.result['lines'])
        values={'arrivals':arrivals,'state':'quality_check' if complete else 'quality_wait'}
        body={'arrival':arr}
    else:
        old,new,r,aid=mapping[b.action]
        if r not in roles or a.id!=aid:fail(403,'RECIPIENT_ONLY','请使用本节点指定的'+r+'账号操作')
        if o.state!=old:fail(409,'STATE_CONFLICT','当前节点不支持此动作，请刷新核对')
        from .change_service import execution_status
        if not execution_status(db,pid,'procurement',o.id,get(db,Version,pid,o.version_id))[0]:fail(409,'SOURCE_VERSION','源方案或需求已更新/撤销，须先复核版本，不可继续审批')
        validate_actors(db,o)
        if b.action in {'return_request','resubmit_request','reject_purchase','fail_quality','rectify'} and not b.reason:fail(422,'REASON_REQUIRED','请填写退回、补正或整改依据')
        values={'state':new};body={'reason':b.reason}
        if b.action=='submit_result':
            if not b.result:fail(422,'RESULT_REQUIRED','请填写下单/合同采购结果')
            lines=b.result.lines
            if sorted(x.line_no for x in lines)!=list(range(1,len(o.lines)+1)):fail(422,'INVALID_LINES','采购结果须逐一对应BOM料行，不能遗漏或重复')
            differences=any(x.quantity!=Decimal(o.lines[x.line_no-1]['quantity']) for x in lines)
            if differences and not b.result.note:fail(422,'DIFFERENCE_REQUIRED','订购数量与需求不一致，须记录差异说明供项目经理复核')
            values['result']=b.result.model_dump(mode='json');body['result']=values['result']
        if b.action=='approve_purchase':
            if any(Decimal(l['quantity'])!=Decimal(o.lines[l['line_no']-1]['quantity']) for l in o.result['lines']) and not b.reason:fail(422,'DIFFERENCE_REQUIRED','数量存在差异，项目经理须明确复核依据')
            values['due_at']=datetime.fromisoformat(max(x['eta'] for x in o.result['lines'])+'T23:59:59+08:00').astimezone(timezone.utc).isoformat()
        if b.action in {'pass_quality','fail_quality','rectify'}:
            files_valid(db,o,b.file_ids,'quality');body['file_ids']=b.file_ids
        if b.action=='archive':
            if not b.archive:fail(422,'ARCHIVE_REQUIRED','请登记采购合同与成本明细')
            files_valid(db,o,b.archive.file_ids,'archive')
            values['archive']=b.archive.model_dump(mode='json');body={'reason':'采购合同及采购成本已归档'}
    if values['state']!=o.state and 'due_at' not in values:values['due_at']=(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat()
    previous=o.state;cas(db,PurchaseOrder,o,b.revision,**values)
    record(store,db,a,o,b.action,rid,body|{'from':previous,'to':o.state})
    return {'id':o.id,'revision':o.revision}
