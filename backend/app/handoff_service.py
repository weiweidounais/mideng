from .pilot_service import workflow_admin
from .pilot_service import business_roles
import hashlib
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from sqlalchemy import select,update
from .pilot_models import Membership,Account,Outbox,utcnow
from .pilot_service import fail,uid
from .handoff_models import Document,Version,Contract,MaterialRow,Arrival,Attachment,BusinessEvent,Issue
from .handoff_schemas import ReqData,SchemeData

EDIT={'requirement':{'市场','商务'},'scheme':{'设计'}}

def role(store,db,a,pid,allowed):
    _,m=store.membership(db,a,pid)
    if not set(business_roles(m.roles)).intersection(allowed):fail(403,'ACTION_FORBIDDEN','当前项目岗位无此业务操作权限')
    return m


def get(db,cls,pid,oid):
    row=db.get(cls,oid)
    if not row or row.project_id!=pid:fail(404,'NOT_ACCESSIBLE','对象不存在或无访问权限')
    return row


def latest(db,doc):
    return db.scalar(select(Version).where(Version.document_id==doc.id,Version.number==doc.version_no)) if doc.version_no else None


def effective_member(db,pid,aid,roles=None):
    a=db.get(Account,aid)
    m=db.scalar(select(Membership).where(Membership.project_id==pid,Membership.account_id==aid))
    now=utcnow()
    return bool(a and a.active and m and m.active and m.valid_from<=now and (not m.valid_until or m.valid_until>now)
                and (not roles or set(business_roles(m.roles)).intersection(roles)))


def source_current(db,v):
    own=get(db,Document,v.project_id,v.document_id)
    if v.number!=own.version_no or v.id in own.withdrawn_versions:return False
    if not v.source_version_id:return True
    req=get(db,Version,v.project_id,v.source_version_id)
    doc=get(db,Document,v.project_id,req.document_id)
    return req.number==doc.version_no and req.id not in doc.withdrawn_versions


def file_view(f):
    return dict(id=f.id,name=f.name,sha256=f.sha256,size=f.size,media_type=f.media_type)


def visible(db,doc,a,roles):
    return doc.version_no>0 or a.id==doc.created_by or bool(set(roles).intersection(EDIT[doc.kind]))


def document_view(db,d,a,roles):
    can_draft=a.id==d.created_by or bool(set(roles).intersection(EDIT[d.kind]))
    versions=[]
    for v in db.scalars(select(Version).where(Version.document_id==d.id).order_by(Version.number.desc())):
        versions.append(dict(id=v.id,document_id=d.id,number=v.number,source_version_id=v.source_version_id,
            previous_id=v.previous_id,body=v.body,attachments=v.attachments,recipients=v.recipients,
            diff_summary=v.diff_summary,published_by=v.published_by,published_at=v.published_at,
            current=v.number==d.version_no and source_current(db,v),withdrawn=v.id in d.withdrawn_versions))
    review=False
    if d.kind=='scheme':
        req=get(db,Document,d.project_id,d.parent_id)
        source=get(db,Version,d.project_id,d.source_version_id)
        review=source.number!=req.version_no or source.id in req.withdrawn_versions
    return dict(id=d.id,kind=d.kind,parent_id=d.parent_id,source_version_id=d.source_version_id,
        revision=d.revision,has_draft=d.has_draft,version_no=d.version_no,needs_review=review,
        draft=d.draft if can_draft and d.has_draft else None,
        draft_files=[file_view(f) for fid in d.draft.get('attachment_ids',[]) if (f:=db.get(Attachment,fid)) and f.project_id==d.project_id] if can_draft and d.has_draft else [],
        versions=versions,created_by=d.created_by)


def arrived(db,row):
    return sum((Decimal(v) for v in db.scalars(select(Arrival.quantity).where(Arrival.row_id==row.id))),Decimal(0))


def row_view(db,r,arrived_total=None):
    return {k:getattr(r,k) for k in ['id','contract_id','line_no','material','spec','quantity','unit','need_by','state','eta','blocked','note','revision']}|{'arrived':str(arrived(db,r) if arrived_total is None else arrived_total)}


def row_views(db,rows):
    """Batch arrival reads while retaining exact Decimal quantities."""
    if not rows:return []
    totals={r.id:Decimal(0) for r in rows}
    for rid,value in db.execute(select(Arrival.row_id,Arrival.quantity).where(Arrival.project_id.in_({r.project_id for r in rows}))):
        if rid in totals:totals[rid]+=Decimal(value)
    return [row_view(db,r,totals[r.id]) for r in rows]


def contract_view(db,c):
    v=get(db,Version,c.project_id,c.version_id)
    return {k:getattr(c,k) for k in ['id','version_id','recipient_id','proxies','created_by','deliverable','quality_rule','require_arrival','sla_hours','triggered_at','original_due_at','due_at','state','paused_at','pause_seconds','return_count','revision']}|{
        'overdue':c.due_at<utcnow() and c.state in {'draft','pending'},'needs_review':not source_current(db,v)}


def event(store,db,a,pid,oid,action,revision,rid,body):
    store.audit(db,a,action,oid,revision,rid,pid)
    db.add(BusinessEvent(id=uid(),project_id=pid,object_id=oid,action=action,body=body,actor_id=a.id))


def notify(db,pid,recipients,title,target_kind=None,target_id=None,version_id=None):
    for aid in set(recipients):db.add(Outbox(id=uid(),project_id=pid,recipient_id=aid,title=title,target_kind=target_kind,target_id=target_id,version_id=version_id))


def cas(db,cls,row,revision,**values):
    result=db.execute(update(cls).where(cls.id==row.id,cls.revision==revision).values(
        **values,revision=cls.revision+1,updated_at=utcnow()).execution_options(synchronize_session=False))
    if result.rowcount!=1:fail(409,'REVISION_CONFLICT','记录已更新，输入已保留，请核对最新版本',current_revision=row.revision)
    db.refresh(row)


def validate_body(db,pid,kind,body):
    from pydantic import ValidationError
    try:
        parsed=(ReqData if kind=='requirement' else SchemeData).model_validate(body)
        data=parsed.model_dump(mode='json')
        if kind=='requirement':
            for field in ['brief_due_at','reply_due_at']:
                value=getattr(parsed,field)
                data[field]=value.isoformat() if value else None
    except ValidationError:
        fail(422,'DOCUMENT_FIELDS','请检查需求/方案类型与其必填内容')
    if len(data['attachment_ids'])!=len(set(data['attachment_ids'])):fail(422,'DUPLICATE_FILE','附件不可重复')
    for fid in data['attachment_ids']:
        f=get(db,Attachment,pid,fid)
        if f.kind!=kind:fail(422,'FILE_KIND','附件用途与对象不一致')
    return data


def doc_create(store,db,a,pid,b,rid):
    role(store,db,a,pid,EDIT[b.kind])
    data=validate_body(db,pid,b.kind,b.body.model_dump(mode='json'))
    if b.kind=='scheme':
        parent=get(db,Document,pid,b.parent_id)
        v=get(db,Version,pid,b.source_version_id)
        if parent.kind!='requirement' or v.document_id!=parent.id or (v.number!=parent.version_no or v.id in parent.withdrawn_versions):
            fail(409,'SOURCE_VERSION','请选择当前正式需求版本')
    elif b.parent_id or b.source_version_id:fail(422,'PARENT_NOT_ALLOWED','需求不能带方案来源关联')
    d=Document(id=uid(),project_id=pid,kind=b.kind,parent_id=b.parent_id,source_version_id=b.source_version_id,
        draft=data,created_by=a.id,updated_by=a.id)
    db.add(d);db.flush();event(store,db,a,pid,d.id,'document.create',d.revision,rid,{'kind':d.kind})
    return document_view(db,d,a,EDIT[d.kind])


def doc_patch(store,db,a,pid,d,b,rid):
    role(store,db,a,pid,EDIT[d.kind])
    if not d.has_draft:fail(409,'FORMAL_IMMUTABLE','正式版本不可覆盖，请先创建修订草稿')
    data=validate_body(db,pid,d.kind,b.body.model_dump(mode='json'))
    source=d.source_version_id
    if d.kind=='scheme':
        source=b.source_version_id or source
        v=get(db,Version,pid,source);parent=get(db,Document,pid,d.parent_id)
        if v.document_id!=parent.id or (v.number!=parent.version_no or v.id in parent.withdrawn_versions):fail(409,'SOURCE_VERSION','请复核当前正式需求版本')
        old=latest(db,d)
        if old and old.source_version_id!=source and not data['review_reason']:
            fail(422,'REVIEW_REASON','需求已升版，请填写复核结论/无影响依据')
    elif b.source_version_id:fail(422,'PARENT_NOT_ALLOWED','需求不能修改来源版本关联')
    cas(db,Document,d,b.revision,draft=data,source_version_id=source,updated_by=a.id)
    event(store,db,a,pid,d.id,'document.edit',d.revision,rid,{'source_version_id':source})
    return document_view(db,d,a,EDIT[d.kind])


def revise(store,db,a,pid,d,b,rid):
    role(store,db,a,pid,EDIT[d.kind])
    if d.has_draft:fail(409,'DRAFT_EXISTS','修订草稿已存在，请继续编辑')
    v=latest(db,d)
    if not v:fail(409,'NO_FORMAL_VERSION','尚无正式版本可修订')
    cas(db,Document,d,b.revision,draft=v.body,has_draft=True,updated_by=a.id)
    event(store,db,a,pid,d.id,'document.revise',d.revision,rid,{'previous_version_id':v.id})
    return document_view(db,d,a,EDIT[d.kind])


def publish(store,db,a,pid,d,b,rid):
    role(store,db,a,pid,{'商务'} if d.kind=='requirement' else {'设计'})
    if not d.has_draft:fail(409,'NO_DRAFT','已发布，请先创建修订草稿')
    data=validate_body(db,pid,d.kind,d.draft)
    required={'设计'} if d.kind=='requirement' else {'项目经理'}
    if len(set(b.recipient_ids))!=len(b.recipient_ids) or not all(effective_member(db,pid,x) for x in b.recipient_ids):
        fail(422,'INVALID_RECIPIENT','接收人必须为有效项目成员且不可重复')
    if not any(effective_member(db,pid,x,required) for x in b.recipient_ids):fail(422,'MISSING_RECIPIENT','缺少有效设计接收人' if d.kind=='requirement' else '缺少有效项目经理接收人')
    if d.kind=='scheme':
        req=get(db,Version,pid,d.source_version_id);parent=get(db,Document,pid,d.parent_id)
        if req.number!=parent.version_no or req.id in parent.withdrawn_versions:fail(409,'SOURCE_VERSION','需求已升版，方案需依据最新版本复核')
        old=latest(db,d)
        if old and old.source_version_id!=d.source_version_id and not data['review_reason']:fail(422,'REVIEW_REASON','缺少复核结论')
    from pathlib import Path
    files=[]
    for fid in data['attachment_ids']:
        item=get(db,Attachment,pid,fid)
        original=Path(store.engine.url.database).resolve().parent/'attachments'/fid
        if not original.is_file():fail(422,'FILE_MISSING','附件原件缺失，不能正式发布')
        if hashlib.sha256(original.read_bytes()).hexdigest()!=item.sha256:fail(422,'FILE_INTEGRITY','附件原件校验失败，不能正式发布')
        files.append(file_view(item))
    previous=latest(db,d);number=d.version_no+1
    cas(db,Document,d,b.revision,version_no=number,has_draft=False,updated_by=a.id)
    v=Version(id=uid(),project_id=pid,document_id=d.id,source_version_id=d.source_version_id,
        previous_id=previous.id if previous else None,number=number,body=data,attachments=files,
        recipients=b.recipient_ids,diff_summary=b.diff_summary,published_by=a.id)
    db.add(v);db.flush()
    event(store,db,a,pid,d.id,'document.publish',d.revision,rid,{'version_id':v.id,'number':number,'diff_summary':b.diff_summary})
    notify(db,pid,b.recipient_ids,f"{'需求' if d.kind=='requirement' else '方案/BOM'}已发布 v{number}：{data['title']}",'document',d.id,v.id)
    return document_view(db,d,a,EDIT[d.kind])


def withdraw(store,db,a,pid,d,b,rid):
    role(store,db,a,pid,{'商务'} if d.kind=='requirement' else {'设计'})
    v=latest(db,d)
    if not v or v.id in d.withdrawn_versions:fail(409,'NO_FORMAL_VERSION','没有可撤销的当前正式版')
    cas(db,Document,d,b.revision,withdrawn_versions=[*d.withdrawn_versions,v.id],updated_by=a.id)
    event(store,db,a,pid,d.id,'document.withdraw',d.revision,rid,{'version_id':v.id,'reason':b.reason})
    notify(db,pid,v.recipients,'正式版本已撤销，待核对：'+v.body['title'],'document',d.id,v.id)
    return document_view(db,d,a,EDIT[d.kind])


def create_contract(store,db,a,pid,b,rid):
    role(store,db,a,pid,{'设计'})
    v=get(db,Version,pid,b.version_id);d=get(db,Document,pid,v.document_id)
    if d.kind!='scheme' or v.number!=d.version_no or not source_current(db,v):fail(409,'SOURCE_VERSION','仅能从当前有效正式方案/BOM创建交接')
    if not v.body.get('bom'):fail(422,'LEGACY_BOM_REQUIRED','旧版交接仅供含历史料表的方案使用；新方案请由项目经理填写采购清单并提交采购需求')
    from .change_service import can_start
    if not can_start(db,pid,v):fail(409,'CHANGE_NOT_CONFIRMED','新来源变更确认未齐，不可新建任务')
    if not all(effective_member(db,pid,x,{'采购'}) for x in [b.recipient_id,*b.proxies]):fail(422,'INVALID_RECIPIENT','接收人及代理须为有效采购岗位')
    due=(datetime.fromisoformat(v.published_at)+timedelta(hours=b.sla_hours)).isoformat()
    c=Contract(id=uid(),project_id=pid,version_id=v.id,recipient_id=b.recipient_id,proxies=list(set(b.proxies)),
        created_by=a.id,updated_by=a.id,deliverable=b.deliverable,quality_rule=b.quality_rule,require_arrival=b.require_arrival,
        sla_hours=b.sla_hours,triggered_at=v.published_at,original_due_at=due,due_at=due)
    db.add(c);db.flush()
    for n,line in enumerate(v.body['bom'],1):
        db.add(MaterialRow(id=uid(),project_id=pid,contract_id=c.id,line_no=n,created_by=a.id,updated_by=a.id,**line))
    event(store,db,a,pid,c.id,'contract.create',c.revision,rid,{'version_id':v.id})
    db.flush();return contract_view(db,c)


def recipient(store,db,a,pid,c):
    role(store,db,a,pid,{'采购'})
    if a.id not in [c.recipient_id,*c.proxies] and not workflow_admin(store,db,a,pid):fail(403,'RECIPIENT_ONLY','仅指定采购接收人或授权代理可操作')


def executable(db,c):
    from .change_service import execution_status
    if not execution_status(db,c.project_id,'contract',c.id,get(db,Version,c.project_id,c.version_id))[0]:fail(409,'SOURCE_VERSION','源需求版本已更新，旧交接需复核处置，不能继续新执行')
    if c.paused_at or c.state=='cancelled':fail(409,'CONTRACT_PAUSED','交接已暂停或取消')


def contract_action(store,db,a,pid,c,b,rid):
    receiver=b.action in {'accept','return','close'}
    if receiver:recipient(store,db,a,pid,c)
    else:role(store,db,a,pid,{'设计','项目经理'} if b.action in {'pause','resume','cancel','reschedule'} else {'设计'})
    if b.action not in {'pause','resume','cancel','reschedule'}:executable(db,c)
    old=c.state;values={'updated_by':a.id}
    transitions={'issue':('draft','pending'),'submit':('pending','submitted'),'accept':('submitted','accepted'),
                 'return':('submitted','pending'),'close':('accepted','closed')}
    if b.action in transitions:
        expected,target=transitions[b.action]
        if old!=expected:fail(409,'STATE_CONFLICT','当前交接状态不支持该操作')
        if b.action=='return' and not b.reason:fail(422,'REASON_REQUIRED','退回必须说明原因')
        if b.action=='close' and c.require_arrival:
            rows=db.scalars(select(MaterialRow).where(MaterialRow.contract_id==c.id)).all()
            if any(r.blocked or arrived(db,r)!=Decimal(r.quantity) for r in rows):fail(422,'INCOMPLETE_ARRIVAL','约定要求全量到货，当前数量或阻塞未处理')
        if b.action=='return':values['return_count']=c.return_count+1
        values['state']=target
    elif b.action in {'pause','resume','cancel','reschedule'}:
        if not b.reason:fail(422,'REASON_REQUIRED','请填写本次操作依据')
        if old in {'closed','cancelled'}:fail(409,'STATE_CONFLICT','已结束交接不能修改')
        if b.action=='pause':
            if c.paused_at:fail(409,'STATE_CONFLICT','已暂停')
            values['paused_at']=utcnow()
        elif b.action=='resume':
            if not c.paused_at:fail(409,'STATE_CONFLICT','未暂停')
            values.update(paused_at=None,pause_seconds=c.pause_seconds+int((datetime.now(timezone.utc)-datetime.fromisoformat(c.paused_at)).total_seconds()))
        elif b.action=='cancel':values['state']='cancelled'
        else:
            if not b.due_at or b.due_at.isoformat()<=c.triggered_at:fail(422,'INVALID_DEADLINE','截止时间须晚于触发时间')
            values['due_at']=b.due_at.isoformat()
    cas(db,Contract,c,b.revision,**values)
    event(store,db,a,pid,c.id,'contract.'+b.action,c.revision,rid,{'from':old,'to':c.state,'reason':b.reason,'due_at':c.due_at})
    notify(db,pid,[c.created_by] if receiver else [c.recipient_id],f'交接状态更新：{b.action}（{c.deliverable}）','contract',c.id,c.version_id)
    return contract_view(db,c)


def row_patch(store,db,a,pid,r,b,rid):
    c=get(db,Contract,pid,r.contract_id);recipient(store,db,a,pid,c);executable(db,c)
    if c.state not in {'pending','submitted','accepted','closed'}:fail(409,'STATE_CONFLICT','交接尚未发出')
    if b.state in {'ordered','arrived'} and c.state not in {'accepted','closed'}:fail(409,'NOT_ACCEPTED','采购执行前需完成交付验收')
    order={'pending':0,'quoted':1,'ordered':2,'arrived':3}
    if order[b.state]<order[r.state]:fail(409,'STATE_CONFLICT','已发生采购进度不能回退覆盖')
    if b.state=='arrived' and arrived(db,r)!=Decimal(r.quantity):fail(422,'ARRIVAL_INCOMPLETE','到货数量尚不完整，请登记实际分批到货')
    if b.blocked and not b.note:fail(422,'REASON_REQUIRED','阻塞必须填写原因')
    if r.blocked and not b.blocked and not b.note:fail(422,'REASON_REQUIRED','解除阻塞须说明依据')
    cas(db,MaterialRow,r,b.revision,state=b.state,eta=b.eta.isoformat() if b.eta else None,blocked=b.blocked,note=b.note,updated_by=a.id)
    event(store,db,a,pid,r.id,'row.update',r.revision,rid,{'state':r.state,'blocked':r.blocked,'note':r.note})
    return row_view(db,r)


def arrival_create(store,db,a,pid,r,b,rid):
    c=get(db,Contract,pid,r.contract_id);recipient(store,db,a,pid,c);executable(db,c)
    if c.state not in {'accepted','closed'} or r.state not in {'ordered','arrived'}:fail(409,'NOT_ORDERED','需完成交付验收及下单后登记到货')
    if r.blocked:fail(409,'ROW_BLOCKED','请先解除料行阻塞并记录依据')
    if b.occurred_at>datetime.now(timezone.utc):fail(422,'FUTURE_ARRIVAL','实际到货时间不能在未来')
    total=arrived(db,r)+b.quantity
    if total>Decimal(r.quantity):fail(422,'OVER_ARRIVAL','到货总量超过本料行约定数量')
    cas(db,MaterialRow,r,b.revision,state='arrived' if total==Decimal(r.quantity) else 'ordered',updated_by=a.id)
    v=Arrival(id=uid(),project_id=pid,row_id=r.id,quantity=str(b.quantity),occurred_at=b.occurred_at.isoformat(),created_by=a.id)
    db.add(v);db.flush();event(store,db,a,pid,r.id,'row.arrival',r.revision,rid,{'arrival_id':v.id,'quantity':v.quantity,'occurred_at':v.occurred_at})
    return row_view(db,r)


def issue_candidates(db,pid):
    found=[];now=utcnow()
    for d in db.scalars(select(Document).where(Document.project_id==pid)):
        if d.kind=='requirement':
            due=d.draft.get('brief_due_at')
            if d.has_draft and due and due<now:found.append((d.id,'brief.overdue',d.created_by,'需求草稿已到交底期限'))
            v=latest(db,d)
            if v and v.body.get('reply_due_at') and v.body['reply_due_at']<now:
                schemes=db.scalars(select(Document).where(Document.parent_id==d.id,Document.version_no>0)).all()
                if not any(source_current(db,latest(db,x)) for x in schemes):
                    for receiver in v.recipients:found.append((d.id,'scheme.missing:'+receiver,receiver,'正式需求尚无当前有效方案'))
        elif d.version_no and not source_current(db,latest(db,d)):
            found.append((d.id,'scheme.review:v'+str(d.version_no),d.created_by,'需求已升版，原方案需复核'))
    for c in db.scalars(select(Contract).where(Contract.project_id==pid)):
        if c.state in {'draft','pending'} and c.due_at<now:found.append((c.id,'contract.overdue:r'+str(c.revision),c.created_by,'交接已超过约定交付期限'))
        if c.state not in {'closed','cancelled'} and not source_current(db,get(db,Version,pid,c.version_id)):
            found.append((c.id,'contract.source',c.created_by,'交接源需求版本已更新，待处置'))
    for r in db.scalars(select(MaterialRow).where(MaterialRow.project_id==pid,MaterialRow.blocked.is_(True))):
        c=get(db,Contract,pid,r.contract_id);found.append((r.id,'row.blocked:r'+str(r.revision),c.recipient_id,'采购料行阻塞：'+r.note))
    from .procurement_models import PurchaseOrder
    from .procurement_service import owner as procurement_owner
    from .change_service import execution_status
    for o in db.scalars(select(PurchaseOrder).where(PurchaseOrder.project_id==pid)):
        if o.state=='archived':continue
        if not execution_status(db,pid,'procurement',o.id,get(db,Version,pid,o.version_id))[0]:
            found.append((o.id,'procurement.source',o.pm_id,'采购来源已更新或撤销，须复核处置'))
        if o.due_at<utcnow():found.append((o.id,'procurement.overdue:'+o.state,procurement_owner(o),'采购节点超时：'+o.title))
    from .change_models import ChangeCase
    for c in db.scalars(select(ChangeCase).where(ChangeCase.project_id==pid)):
        if c.state in {'closed','cancelled'}:continue
        due=c.draft.get('emergency_due_at')
        if c.draft.get('emergency') and not c.draft.get('approval') and due and due<utcnow():found.append((c.id,'change.emergency',c.created_by,'紧急变更授权补录超时'))
    return found


def reconcile(db,pid=None):
    from .pilot_models import Project
    pids=[pid] if pid else list(db.scalars(select(Project.id)))
    for project_id in pids:
        candidates=issue_candidates(db,project_id);active=set()
        for oid,rule,owner,title in candidates:
            active.add((oid,rule));v=db.scalar(select(Issue).where(Issue.project_id==project_id,Issue.object_id==oid,Issue.rule==rule))
            if not v:
                v=Issue(id=hashlib.sha256((project_id+oid+rule).encode()).hexdigest()[:32],project_id=project_id,object_id=oid,rule=rule,owner_id=owner,title=title)
                db.add(v)
            else:v.active=True;v.closed_at=None;v.title=title
        for v in db.scalars(select(Issue).where(Issue.project_id==project_id,Issue.active.is_(True))):
            if (v.object_id,v.rule) not in active:v.active=False;v.closed_at=utcnow()
