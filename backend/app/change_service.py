import copy,hashlib
from pathlib import Path
from datetime import datetime,timezone,timedelta
from sqlalchemy import select
from .pilot_models import Todo,Membership,utcnow
from .pilot_service import uid,fail
from .handoff_models import Document,Version,Contract
from .handoff_service import get,role,effective_member,source_current,cas,notify,file_view
from .procurement_models import PurchaseOrder
from .change_models import ChangeCase,ChangeVersion,ChangeAck,ChangeDisposition,ChangeFile,ChangeEvent
IMPACT_ROLES={'technical':{'设计'},'cost':{'商务','财务'},'schedule':{'项目经理'},'quality':{'质量'}}

def source_info(db,pid,data):
    old=get(db,Version,pid,data['old_version_id']);new=get(db,Version,pid,data['new_version_id'])
    if old.document_id!=new.document_id or old.number>=new.number or not source_current(db,new):fail(409,'CHANGE_SOURCE','须选择同一文档的旧正式版与当前新版')
    targets=[{'key':'version:'+old.id,'title':old.body['title']+' · v'+str(old.number),'stage':'正式版本','owner_id':old.published_by,'role':'设计' if get(db,Document,pid,old.document_id).kind=='scheme' else '商务'}]
    related=[v.id for v in db.scalars(select(Version).where(Version.project_id==pid)) if v.document_id==old.document_id or (v.source_version_id and db.get(Version,v.source_version_id).document_id==old.document_id)]
    for o in db.scalars(select(PurchaseOrder).where(PurchaseOrder.project_id==pid,PurchaseOrder.version_id.in_(related))):
        targets.append({'key':'procurement:'+o.id,'title':o.title,'stage':o.state,'owner_id':o.purchase_id if o.result else o.pm_id,'role':'采购' if o.result else '项目经理','recipients':[o.pm_id,o.purchase_id,o.quality_id,o.commerce_id]})
    for c in db.scalars(select(Contract).where(Contract.project_id==pid,Contract.version_id.in_(related))):
        targets.append({'key':'contract:'+c.id,'title':c.deliverable,'stage':c.state,'owner_id':c.recipient_id if c.state in {'accepted','closed'} else c.created_by,'role':'采购' if c.state in {'accepted','closed'} else '设计','recipients':[c.created_by,c.recipient_id,*c.proxies]})
    from .trace_models import Spool,TraceOrder
    for spool in db.scalars(select(Spool).join(TraceOrder,TraceOrder.id==Spool.order_id).where(Spool.project_id==pid,TraceOrder.version_id.in_(related))):
        order=db.get(TraceOrder,spool.order_id)
        owner,position=(order.site_id,'现场') if spool.state in {'shipped','installed','hold'} else (order.quality_id,'质量') if spool.state in {'inspection','tested','completed','scrapped'} else (order.factory_id,'工厂')
        targets.append({'key':'spool:'+spool.id,'title':'管段 '+spool.code,'stage':spool.state,'owner_id':owner,'role':position,'recipients':[order.pm_id,order.factory_id,order.site_id,order.quality_id]})
    replacements=[new.id]
    if new.source_version_id:replacements.append(new.source_version_id)
    replacements.extend(v.id for v in db.scalars(select(Version).where(Version.project_id==pid,Version.source_version_id==new.id)) if source_current(db,v))
    return targets,sorted(set(replacements))

def required(data):
    ids={t['owner_id'] for t in data['targets']}
    for t in data['targets']:ids.update(t.get('recipients',[]))
    ids.update(v['actor_id'] for v in data.get('impacts',{}).values())
    return sorted(ids)

def all_acked(db,v):
    ids=set(v.body['recipients']);acked=set(db.scalars(select(ChangeAck.actor_id).where(ChangeAck.version_id==v.id)))
    return ids<=acked and all(r['delivered_at'] and r['confirmed_at'] for r in receipts(db,v))

def receipts(db,v):
    result=[]
    for aid in v.body['recipients']:
        delivered=db.scalar(select(Todo).where(Todo.target_id==v.case_id,Todo.version_id==v.id,Todo.recipient_id==aid))
        ack=db.scalar(select(ChangeAck).where(ChangeAck.version_id==v.id,ChangeAck.actor_id==aid))
        result.append({'account_id':aid,'delivered_at':delivered.created_at if delivered and effective_member(db,v.project_id,aid) else None,'confirmed_at':ack.at if ack else None})
    return result

def valid_files(db,c,ids,purpose,version=None):
    if not ids:fail(422,'EVIDENCE_REQUIRED','缺少批准或执行原件')
    for fid in ids:
        f=get(db,ChangeFile,c.project_id,fid)
        if f.case_id!=c.id or f.purpose!=purpose or (version and f.version_id!=version):fail(422,'FILE_SCOPE','证据须属于当前变更、用途和发布版本')
        p=Path(f.path)
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=f.sha256:fail(409,'ORIGINAL_MISSING','证据原件缺失或哈希不符')

def view(db,c,a,roles):
    money=bool(set(roles)&{'商务','财务'})
    def redact(b):
        b=copy.deepcopy(b)
        if not money:
            if 'cost' in b.get('impacts',{}):b['impacts']['cost']['basis']='成本影响结论由商务/财务确认；明细仅授权岗位可读'
            if b.get('approval'):b['approval']['basis']='既有批准已登记，受限原件仅授权岗位可读'
        return b
    versions=[]
    for v in db.scalars(select(ChangeVersion).where(ChangeVersion.case_id==c.id).order_by(ChangeVersion.number.desc())):
        ds=[{k:getattr(d,k) for k in ['id','target_key','decision','executor_id','reason','file_ids','submitted_at','verified_at','verified_by']} for d in db.scalars(select(ChangeDisposition).where(ChangeDisposition.version_id==v.id))]
        versions.append({'id':v.id,'number':v.number,'body':redact(v.body),'published_at':v.published_at,'receipts':receipts(db,v),'dispositions':ds})
    files=[]
    for f in db.scalars(select(ChangeFile).where(ChangeFile.case_id==c.id)):
        files.append(file_view(f)|{'name':f.name if not f.restricted or money else '受限原件（仅商务/财务可下载）','purpose':f.purpose,'restricted':f.restricted,'version_id':f.version_id})
    draft_visible=c.created_by==a.id or bool(set(roles)&{'项目经理','设计','商务','质量','财务'})
    visible_draft=c.draft if draft_visible or not versions else versions[0]['body']
    return dict(id=c.id,project_id=c.project_id,revision=c.revision,state=c.state,number=c.number,draft=redact(visible_draft),current=next((v for v in versions if v['id']==c.current_version_id),None),versions=versions,required_recipient_ids=required(c.draft),files=files,events=[dict(id=e.id,action=e.action,actor_id=e.actor_id,at=e.at,body=e.body) for e in db.scalars(select(ChangeEvent).where(ChangeEvent.case_id==c.id).order_by(ChangeEvent.at))])

def record(store,db,a,c,name,rid,body=None):
    store.audit(db,a,'change.'+name,c.id,c.revision,rid,c.project_id)
    db.add(ChangeEvent(id=uid(),project_id=c.project_id,case_id=c.id,actor_id=a.id,action=name,body=body or {}))

def create(store,db,a,pid,b,rid):
    role(store,db,a,pid,{'项目经理'});data=b.model_dump(mode='json');targets,replacements=source_info(db,pid,data)
    data|={'targets':targets,'replacements':replacements,'impacts':{},'approval':None,'waiting':'external_approval' if b.emergency else 'none','emergency_due_at':(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat() if b.emergency else None}
    c=ChangeCase(id=uid(),project_id=pid,draft=data,created_by=a.id);db.add(c);db.flush();record(store,db,a,c,'create',rid)
    if b.emergency:notify(db,pid,[a.id],'紧急变更待补录既有授权（建议24小时内）：'+b.title,'change',c.id)
    return {'id':c.id,'revision':c.revision}

def act(store,db,a,pid,c,b,rid):
    m=store.membership(db,a,pid)[1];draft=copy.deepcopy(c.draft);state=c.state
    v=db.get(ChangeVersion,c.current_version_id) if c.current_version_id else None
    pm=b.action in {'approval','publish','plan','verify','request_close','close','revise','cancel','wait'}
    if pm:role(store,db,a,pid,{'项目经理'})
    body={};values={}
    if b.action=='impact':
        if state not in {'analysis','await_approval'}:fail(409,'STATE_CONFLICT','仅分析阶段可确认专业影响')
        if not b.category or not set(m.roles)&IMPACT_ROLES[b.category]:fail(403,'PROFESSIONAL_ONLY','请使用对应专业岗位账号确认')
        if b.has_impact is None or not b.reason:fail(422,'IMPACT_REQUIRED','须明确有无影响及依据，不得以待补充发布')
        allowed={t['key'] for t in draft['targets']}
        if not set(b.target_keys)<=allowed or (b.has_impact and not b.target_keys):fail(422,'IMPACT_TARGETS','有影响须列出实际受影响对象')
        draft['impacts'][b.category]={'has_impact':b.has_impact,'basis':b.reason,'target_keys':b.target_keys,'actor_id':a.id,'at':utcnow()}
        state='await_approval' if len(draft['impacts'])==4 else 'analysis';body={'category':b.category}
    elif b.action=='approval':
        if state!='await_approval' or len(draft['impacts'])!=4:fail(409,'IMPACT_INCOMPLETE','四类专业影响确认齐全后才能登记既有批准')
        if not b.approval_no or not b.reason:fail(422,'APPROVAL_REQUIRED','请填写既有批准编号与登记依据')
        valid_files(db,c,b.file_ids,'approval');draft['approval']={'number':b.approval_no,'basis':b.reason,'file_ids':b.file_ids,'registered_by':a.id,'at':utcnow()};state='approved'
    elif b.action=='publish':
        if state!='approved' or not draft['approval']:fail(409,'APPROVAL_REQUIRED','须先登记有效既有批准依据')
        latest_targets,replacements=source_info(db,pid,draft)
        if {t['key'] for t in latest_targets}!={t['key'] for t in draft['targets']} or set(replacements)!=set(draft['replacements']):fail(409,'IMPACT_SCOPE_CHANGED','分析后的对象或新版本关联已变化，须起修订重新确认')
        draft['targets']=latest_targets
        valid_files(db,c,draft['approval']['file_ids'],'approval')
        for cat,impact in draft['impacts'].items():
            if not effective_member(db,pid,impact['actor_id'],IMPACT_ROLES[cat]):fail(422,'PROFESSIONAL_EXPIRED','专业确认账号授权已失效，须重新核对')
        rec=set(b.recipient_ids)
        if not set(required(draft))<=rec or not rec or not all(effective_member(db,pid,x) for x in rec):fail(422,'MISSING_RECIPIENT','缺少受影响对象/专业确认的必需接收人，或账号已失效')
        frozen=copy.deepcopy(draft);frozen['recipients']=sorted(rec);frozen['published_by']=a.id;frozen['previous_version_id']=c.current_version_id
        keys={t['key'] for t in frozen['targets']}
        frozen['supersedes']=[other.current_version_id for other in db.scalars(select(ChangeCase).where(ChangeCase.project_id==pid,ChangeCase.current_version_id.is_not(None))) if other.id!=c.id and any(t['key'] in keys for t in db.get(ChangeVersion,other.current_version_id).body['targets'])]
        v=ChangeVersion(id=uid(),project_id=pid,case_id=c.id,number=c.number+1,body=frozen);db.add(v);db.flush()
        values|={'number':v.number,'current_version_id':v.id};state='published'
        notify(db,pid,rec,'变更已发布 v'+str(v.number)+'：'+draft['title'],'change',c.id,v.id)
    elif b.action=='revise':
        if not b.replacement:fail(422,'REVISION_REQUIRED','请明确修订后的版本、标题与差异原因')
        data=b.replacement.model_dump(mode='json');targets,replacements=source_info(db,pid,data)
        draft=data|{'targets':targets,'replacements':replacements,'impacts':{},'approval':None,'waiting':'none'};state='analysis'
    elif b.action=='cancel':
        if not b.reason:fail(422,'REASON_REQUIRED','取消必须记录依据')
        if state in {'closed','cancelled'}:fail(409,'STATE_CONFLICT','已结束变更不可取消')
        state='cancelled';body={'reason':b.reason}
    elif b.action=='wait':
        if not b.reason:fail(422,'REASON_REQUIRED','外部等待须记录依据')
        if state in {'closed','cancelled'}:fail(409,'STATE_CONFLICT','已结束变更不可修改')
        draft['waiting']=b.waiting;body={'waiting':b.waiting,'reason':b.reason}
    else:
        if not v or b.version_id!=v.id or state not in {'published','handling','verifying'}:fail(409,'CHANGE_VERSION','须针对当前有效发布版本操作，旧确认不能沿用')
        if b.action=='ack':
            if a.id not in v.body['recipients']:fail(403,'RECIPIENT_ONLY','仅本版冻结接收人可本人确认')
            if not any(r['account_id']==a.id and r['delivered_at'] for r in receipts(db,v)):fail(409,'NOT_DELIVERED','站内待办尚未送达，不能冒充确认')
            if not db.scalar(select(ChangeAck).where(ChangeAck.version_id==v.id,ChangeAck.actor_id==a.id)):
                db.add(ChangeAck(id=uid(),version_id=v.id,actor_id=a.id))
            state='handling' if state=='published' else state
        elif b.action in {'plan','execute','verify'}:
            target=next((t for t in v.body['targets'] if t['key']==b.target_key),None)
            if not target:fail(422,'TARGET_REQUIRED','请选择本版实际受影响对象')
            d=db.scalar(select(ChangeDisposition).where(ChangeDisposition.version_id==v.id,ChangeDisposition.target_key==b.target_key))
            if b.action=='plan':
                if d:fail(409,'DISPOSITION_EXISTS','处置计划已冻结；变更须起新修订')
                if not b.decision or not b.reason:fail(422,'DISPOSITION_REQUIRED','须选择处置方式并记录批准依据')
                if not effective_member(db,pid,target['owner_id'],{target['role']}):fail(422,'EXECUTOR_EXPIRED','对象责任人授权已失效，请核对后起修订')
                d=ChangeDisposition(id=uid(),project_id=pid,version_id=v.id,target_key=b.target_key,decision=b.decision,executor_id=target['owner_id'],reason=b.reason);db.add(d)
                notify(db,pid,[d.executor_id],'变更对象待处置：'+target['title'],'change',c.id,v.id)
            elif b.action=='execute':
                if not d or a.id!=d.executor_id or target['role'] not in m.roles:fail(403,'EXECUTOR_ONLY','仅已指定对象责任岗位可提交处置证据')
                if not db.scalar(select(ChangeAck).where(ChangeAck.version_id==v.id,ChangeAck.actor_id==a.id)):fail(409,'ACK_REQUIRED','须先本人确认本版变更，再提交处置证据')
                if d.submitted_at:fail(409,'DISPOSITION_IMMUTABLE','已提交处置不可覆盖，请起修订保留历史')
                if not b.reason:fail(422,'REASON_REQUIRED','请记录实际处置说明')
                valid_files(db,c,b.file_ids,'execution',v.id);d.file_ids=b.file_ids;d.reason+='；实际处置：'+b.reason;d.submitted_at=utcnow()
            else:
                if not d or not d.submitted_at:fail(409,'DISPOSITION_INCOMPLETE','实际处置证据提交后才能核对')
                valid_files(db,c,d.file_ids,'execution',v.id);d.verified_at=utcnow();d.verified_by=a.id
            state='verifying' if state=='verifying' else 'handling';body={'target_key':b.target_key,'decision':d.decision}
        elif b.action in {'request_close','close'}:
            if not all_acked(db,v):fail(409,'ACK_INCOMPLETE','必需接收人本版送达/本人确认未齐')
            source_info(db,pid,v.body);valid_files(db,c,v.body['approval']['file_ids'],'approval')
            ds=db.scalars(select(ChangeDisposition).where(ChangeDisposition.version_id==v.id)).all()
            if len(ds)!=len(v.body['targets']) or any(not d.submitted_at for d in ds):fail(409,'DISPOSITION_INCOMPLETE','逐对象处置证据未齐')
            if b.action=='close':
                if state!='verifying' or any(not d.verified_at for d in ds):fail(409,'VERIFY_INCOMPLETE','PM须逐对象核对后才能关闭')
                for d in ds:valid_files(db,c,d.file_ids,'execution',v.id)
                state='closed'
            else:state='verifying'
        else:fail(409,'STATE_CONFLICT','当前节点不能执行该动作')
    cas(db,ChangeCase,c,b.revision,draft=draft,state=state,**values)
    record(store,db,a,c,b.action,rid,body|{'version_id':v.id if v else None})
    return {'id':c.id,'revision':c.revision}

def related_change(db,pid,kind,oid):
    key=kind+':'+oid
    candidates=[]
    for c in db.scalars(select(ChangeCase).where(ChangeCase.project_id==pid,ChangeCase.current_version_id.is_not(None))):
        v=db.get(ChangeVersion,c.current_version_id)
        if any(t['key']==key for t in v.body['targets']):candidates.append((v.published_at,c,v))
    return max(candidates,key=lambda x:x[0])[1:] if candidates else None

def execution_status(db,pid,kind,oid,version):
    key=kind+':'+oid
    related=related_change(db,pid,kind,oid)
    if not related:return source_current(db,version),'来源有效' if source_current(db,version) else '来源已更新或撤销'
    c,v=related
    d=db.scalar(select(ChangeDisposition).where(ChangeDisposition.version_id==v.id,ChangeDisposition.target_key==key))
    if c.state=='cancelled' or not source_current(db,get(db,Version,pid,v.body['new_version_id'])):return False,'变更已取消或被更新，待重新核对'
    if not d or not d.verified_at or not all_acked(db,v):return False,'变更 v'+str(v.number)+' 待接收确认或对象处置核对'
    if d.decision!='continue':return False,'已按批准处置停用：'+d.decision
    try:
        valid_files(db,c,v.body['approval']['file_ids'],'approval')
        valid_files(db,c,d.file_ids,'execution',v.id)
    except Exception:return False,'批准或处置原件校验不符'
    return True,'已按变更 v'+str(v.number)+' 核对继续使用；原版本保留'

def can_start(db,pid,v):
    lineage=[v]+([db.get(Version,v.source_version_id)] if v.source_version_id else [])
    if not any(x.previous_id for x in lineage):return True
    candidates=[]
    for c in db.scalars(select(ChangeCase).where(ChangeCase.project_id==pid,ChangeCase.current_version_id.is_not(None))):
        cv=db.get(ChangeVersion,c.current_version_id)
        if v.id in cv.body['replacements']:candidates.append((cv.published_at,c,cv))
    if not candidates:return False
    _,c,cv=max(candidates,key=lambda x:x[0])
    if c.state=='cancelled' or not source_current(db,get(db,Version,pid,cv.body['new_version_id'])) or not all_acked(db,cv):return False
    ds=db.scalars(select(ChangeDisposition).where(ChangeDisposition.version_id==cv.id)).all()
    if len(ds)!=len(cv.body['targets']) or any(not d.verified_at for d in ds):return False
    try:
        valid_files(db,c,cv.body['approval']['file_ids'],'approval')
        for d in ds:valid_files(db,c,d.file_ids,'execution',cv.id)
    except Exception:return False
    return True
