from .pilot_service import workflow_admin
from .pilot_service import business_roles
import copy,hashlib,json
from pathlib import Path
from sqlalchemy import select
from .pilot_service import uid,fail
from .pilot_models import utcnow
from .handoff_models import Version,Document
from .handoff_service import get,role,effective_member,source_current,cas,notify,file_view
from .trace_models import TraceTemplate,TraceOrder,Spool,TraceWeld,TraceRecord,TraceEvent,TraceFile
from .change_service import can_start,execution_status,related_change
END={'scrapped','retired'}
FACT_ROLES={'material':'工厂','weld':'工厂','fabrication':'工厂','pressure':'现场'}

def facts(db,s):return list(db.scalars(select(TraceRecord).where(TraceRecord.spool_id==s.id).order_by(TraceRecord.received_at,TraceRecord.id)))
def effective(rows):
    result={}
    for r in rows:result[r.corrects_id or r.id]=r
    return list(result.values())
def latest(rows,kind):return next((r for r in reversed(rows) if r.kind==kind),None)
def fingerprint(rows):return hashlib.sha256(json.dumps([(r.id,r.data,r.file_ids) for r in effective(rows) if r.kind in {'material','weld','fabrication','repair'}],sort_keys=True).encode()).hexdigest()
def originals(db,s,ids,required=True):
    if required and not ids:fail(422,'REPORT_REQUIRED','缺少本管段原件报告')
    for fid in ids:
        f=get(db,TraceFile,s.project_id,fid)
        if f.spool_id!=s.id:fail(422,'REPORT_SCOPE','原件须属于本管段')
        p=Path(f.path)
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=f.sha256:fail(409,'ORIGINAL_CHANGED','原件缺失或校验不符')
def assigned(store,db,a,s,r):
    role(store,db,a,s.project_id,{r});o=get(db,TraceOrder,s.project_id,s.order_id)
    if a.id!=getattr(o,{'工厂':'factory_id','现场':'site_id','质量':'quality_id','项目经理':'pm_id'}[r]) and not workflow_admin(store,db,a,s.project_id):fail(403,'ASSIGNED_ONLY','仅本预制订单指定的负责账号可执行')
    return o

def source(db,s):
    o=get(db,TraceOrder,s.project_id,s.order_id);return execution_status(db,s.project_id,'spool',s.id,get(db,Version,s.project_id,o.version_id))
def require_source(db,s):
    ok,message=source(db,s)
    if not ok:fail(409,'SOURCE_CHANGED',message+'，请由项目经理完成变更处置')
def requirements(db,s,stage=None,rows=None):
    t=get(db,TraceTemplate,s.project_id,s.template_id);rows=rows if rows is not None else facts(db,s);eff=effective(rows);missing=[]
    material=latest(eff,'material');welds=[r for r in eff if r.kind=='weld'];fab=latest(eff,'fabrication')
    if not material:missing.append('材料批次与证书')
    if (stage or s.state)!='registered':
        if not fab:missing.append('预制设备与记录')
        if t.welding and not welds:missing.append('适用焊缝/焊工资格/焊材批次/设备')
    for r in eff:
        try:originals(db,s,r.file_ids,required=r.kind in {'material','pressure','repair'})
        except Exception:missing.append('原件缺失或校验不符：'+r.kind)
    return list(dict.fromkeys(missing))
def quality_valid(db,s,rows=None):
    rows=rows if rows is not None else facts(db,s);q=latest(rows,'inspection')
    if not q or not q.data['passed'] or q.data['fingerprint']!=fingerprint(rows):return False
    welds={w.id for w in db.scalars(select(TraceWeld).where(TraceWeld.spool_id==s.id))}
    if set(q.data['weld_ids'])!=welds:return False
    try:originals(db,s,q.file_ids)
    except Exception:return False
    return not requirements(db,s,'inspection',rows)
def pressure_valid(db,s,rows):
    p=latest(effective(rows),'pressure');q=latest(rows,'pressure_result')
    if not p or not q or not q.data['passed'] or q.data['record_id']!=p.id or q.data['fingerprint']!=fingerprint(rows):return False
    try:originals(db,s,p.file_ids);originals(db,s,q.file_ids)
    except Exception:return False
    return True

def owner(db,s):
    o=get(db,TraceOrder,s.project_id,s.order_id)
    if s.state in {'inspection','tested','completed'}:return o.quality_id
    if s.state=='installed' and latest(facts(db,s),'pressure') and not pressure_valid(db,s,facts(db,s)):return o.quality_id
    if s.state in {'shipped','installed','hold'}:return o.site_id
    return o.factory_id

def view(db,s,roles,history=True):
    rows=facts(db,s);ok,message=source(db,s);related=related_change(db,s.project_id,'spool',s.id)
    records=[]
    for r in (rows if history else []):
        data=copy.deepcopy(r.data)
        if not set(roles)&{'工厂','现场','质量','项目经理'}:data.pop('welder_code',None)
        records.append({k:getattr(r,k) for k in ['id','kind','file_ids','source','occurred_at','received_at','actor_id','corrects_id']}|{'data':data})
    missing=requirements(db,s,rows=rows)
    if s.state in {'ready','shipped','installed','tested','completed'} and not quality_valid(db,s,rows):missing.append('质量放行依据待复核')
    t=get(db,TraceTemplate,s.project_id,s.template_id)
    if s.state in {'tested','completed'} and t.pressure and not pressure_valid(db,s,rows):missing.append('适用试压待质量确认')
    return {k:getattr(s,k) for k in ['id','project_id','order_id','template_id','code','revision','state','parents']}|{'children':[x.id for x in db.scalars(select(Spool).where(Spool.project_id==s.project_id)) if s.id in x.parents], 'records':records,'welds':[dict(id=w.id,code=w.code) for w in db.scalars(select(TraceWeld).where(TraceWeld.spool_id==s.id))] if history else [], 'files':[file_view(f) for f in db.scalars(select(TraceFile).where(TraceFile.spool_id==s.id))] if history else [], 'events':[dict(id=e.id,action=e.action,body=e.body,actor_id=e.actor_id,at=e.at) for e in db.scalars(select(TraceEvent).where(TraceEvent.spool_id==s.id).order_by(TraceEvent.at))] if history else [], 'missing':missing,'source_ok':ok,'source_status':message,'owner_id':owner(db,s),'change_id':related[0].id if related else None}
def metrics(views):
    completed=[s for s in views if s['state']=='completed'];progress=[s for s in views if s['state'] not in END|{'completed'}];valid=sum(not s['missing'] and s['source_ok'] for s in completed)
    return {'definition':'F5-v1：完成件完整率仅统计completed；在制按当前阶段；报废/拆并另列；零分母N/A','completed_total':len(completed),'completed_valid':valid,'completed_rate':valid/len(completed) if completed else None,'in_progress_total':len(progress),'in_progress_ready':sum(not s['missing'] and s['source_ok'] for s in progress),'scrapped':sum(s['state']=='scrapped' for s in views),'retired':sum(s['state']=='retired' for s in views)}
def event(store,db,a,s,action,rid,body=None):
    store.audit(db,a,'trace.'+action,s.id,s.revision,rid,s.project_id);db.add(TraceEvent(id=uid(),project_id=s.project_id,spool_id=s.id,actor_id=a.id,action=action,body=body or {}));notify(db,s.project_id,[owner(db,s)],'管段'+s.code+'：'+action,'spool',s.id)
def append(db,a,s,kind,data,ids,occurred=None,source_type='manual',corrects=None):
    r=TraceRecord(id=uid(),project_id=s.project_id,spool_id=s.id,kind=kind,data=data,file_ids=ids,source=source_type,occurred_at=occurred or utcnow(),actor_id=a.id,corrects_id=corrects);db.add(r);db.flush();return r

def template(store,db,a,pid,b,rid):
    role(store,db,a,pid,{'质量'});t=TraceTemplate(id=uid(),project_id=pid,**b.model_dump(exclude={'photo_ids'}),approved_by=a.id);db.add(t);db.flush();store.audit(db,a,'trace.template.confirm',t.id,1,rid,pid)
    from .template_photos import attach
    attach(store,db,a,t,b.photo_ids,rid)
    return {'id':t.id,'revision':1}
def order(store,db,a,pid,b,rid):
    role(store,db,a,pid,{'项目经理'});v=get(db,Version,pid,b.version_id)
    if get(db,Document,pid,v.document_id).kind!='scheme' or not source_current(db,v) or not can_start(db,pid,v):fail(409,'SOURCE_CHANGED','须使用当前正式方案并完成所需变更确认与处置')
    for aid,r in [(b.factory_id,'工厂'),(b.site_id,'现场'),(b.quality_id,'质量')]:
        if not effective_member(db,pid,aid,{r}):fail(422,'INVALID_RECIPIENT','工厂、现场、质量须为有效项目岗位')
    o=TraceOrder(id=uid(),project_id=pid,**b.model_dump(),pm_id=a.id);db.add(o);db.flush();store.audit(db,a,'trace.order',o.id,1,rid,pid);notify(db,pid,[o.factory_id],'预制订单待逐件登记：'+o.code,'trace_order',o.id,v.id);return {'id':o.id,'revision':1}
def spool(store,db,a,pid,b,rid):
    o=get(db,TraceOrder,pid,b.order_id);role(store,db,a,pid,{'工厂'})
    if o.factory_id!=a.id and not workflow_admin(store,db,a,pid):fail(403,'ASSIGNED_ONLY','仅指定工厂可建管段')
    t=get(db,TraceTemplate,pid,b.template_id)
    if t.approved_by!=o.quality_id and not workflow_admin(store,db,a,pid):fail(422,'TEMPLATE_OWNER','请使用本订单质量负责人确认的模板')
    v=get(db,Version,pid,o.version_id)
    if not source_current(db,v) or not can_start(db,pid,v):fail(409,'SOURCE_CHANGED','旧来源不能创建新管段，请核对新版订单与变更')
    s=Spool(id=uid(),project_id=pid,**b.model_dump(),created_by=a.id);db.add(s);db.flush();event(store,db,a,s,'create',rid);return {'id':s.id,'revision':s.revision}

def record(store,db,a,s,b,rid):
    rows=facts(db,s)
    r='现场' if b.kind=='repair' and latest(rows,'shipment') else '工厂' if b.kind=='repair' else FACT_ROLES[b.kind]
    assigned(store,db,a,s,r)
    if s.state in END:fail(409,'SPOOL_ENDED','已报废或拆并管段仅保留履历')
    if not b.corrects_id:require_source(db,s)
    data=b.data.model_dump();state=s.state;t=get(db,TraceTemplate,s.project_id,s.template_id)
    required={'material':['batch'],'weld':['weld_code','welder_code','consumable_batch','equipment'],'fabrication':['equipment','description'],'repair':['description'],'pressure':['equipment','description']}
    if any(not data[k] for k in required[b.kind]):fail(422,'FACT_INCOMPLETE','本工序必填追溯字段未齐')
    if b.kind=='weld' and not t.welding:fail(409,'NOT_APPLICABLE','本已确认模板不适用焊接，需先核对模板而非任意加减工序')
    if b.kind=='pressure' and not t.pressure:fail(409,'NOT_APPLICABLE','本模板不适用试压')
    originals(db,s,b.file_ids,required=b.kind in {'material','repair','pressure'})
    if b.source=='template_import':
        matched=False
        from datetime import datetime
        for fid in b.file_ids:
            f=get(db,TraceFile,s.project_id,fid)
            if Path(f.name).suffix.lower()=='.json':
                try:
                    raw=json.loads(Path(f.path).read_text());from .trace_schemas import FactData
                    matched=matched or (raw['kind']==b.kind and FactData.model_validate(raw['data']).model_dump()==data and datetime.fromisoformat(raw['occurred_at'])==b.occurred_at)
                except (ValueError,KeyError,TypeError):pass
        if not matched:fail(422,'IMPORT_PROVENANCE','模板导入须关联内容与本次工序一致的JSON原件')
    if b.corrects_id:
        old=get(db,TraceRecord,s.project_id,b.corrects_id)
        if old.spool_id!=s.id or old.kind!=b.kind or old.corrects_id or not b.correction_reason:fail(422,'CORRECTION_SCOPE','更正须指向同管段原始工序记录并说明原因')
        if b.kind=='weld' and data['weld_code']!=old.data['weld_code']:fail(422,'CODE_IMMUTABLE','焊缝编码不可通过更正复用')
        data['correction_reason']=b.correction_reason
        if state in {'ready','inspection'}:state='inspection'
        if state in {'tested','completed'}:state='installed'
    else:
        allowed={'material':{'registered','fabricating','rework'},'weld':{'fabricating','rework'},'fabrication':{'fabricating','rework'},'repair':{'rework','hold','installed'},'pressure':{'installed'}}
        if state not in allowed[b.kind]:fail(409,'STATE_CONFLICT','当前阶段不能登记此工序')
        if b.kind in {'material','fabrication'} and latest(effective(rows),b.kind):fail(409,'USE_CORRECTION','已有记录，请通过追加更正保留原值')
        if b.kind=='weld':db.add(TraceWeld(id=uid(),project_id=s.project_id,spool_id=s.id,code=data['weld_code']))
    append(db,a,s,b.kind,data,b.file_ids,b.occurred_at.isoformat(),b.source,b.corrects_id);cas(db,Spool,s,b.revision,state=state);event(store,db,a,s,'correction' if b.corrects_id else b.kind,rid,{'corrects_id':b.corrects_id});return {'id':s.id,'revision':s.revision}

def act(store,db,a,s,b,rid):
    rows=facts(db,s);state=s.state;t=get(db,TraceTemplate,s.project_id,s.template_id)
    r={'start':'工厂','submit_inspection':'现场' if latest(rows,'shipment') else '工厂','inspect':'质量','ship':'工厂','install':'现场','confirm_pressure':'质量','complete':'质量','scrap':'质量','label':'工厂'}[b.action]
    o=assigned(store,db,a,s,r)
    if state in END:fail(409,'SPOOL_ENDED','报废/拆并对象不能继续或重新发码')
    if b.action not in {'scrap','label'}:require_source(db,s)
    data={};ids=b.file_ids
    if b.action=='start':
        if state!='registered':fail(409,'STATE_CONFLICT','仅已登记管段可开工')
        if requirements(db,s,'registered'):fail(409,'MATERIAL_MISSING','开工前须有材料批次及有效证书')
        state='fabricating'
    elif b.action=='submit_inspection':
        if state not in {'fabricating','rework','hold'}:fail(409,'STATE_CONFLICT','当前不能提交待检')
        if requirements(db,s,'inspection'):fail(409,'FACT_INCOMPLETE','材料、预制或适用焊缝资料未齐')
        q=latest(rows,'inspection');repair=latest(rows,'repair')
        if q and not q.data['passed'] and (not repair or repair.received_at<=q.received_at):fail(409,'REPAIR_REQUIRED','不合格后须追加真实返修记录及原件')
        state='inspection'
    elif b.action=='inspect':
        if state not in {'inspection','shipped','installed','tested','completed'}:fail(409,'STATE_CONFLICT','当前不在检测/更正复核节点')
        if b.passed is None or not b.reason:fail(422,'RESULT_REQUIRED','质量须明确结果及依据')
        if requirements(db,s,'inspection'):fail(409,'FACT_INCOMPLETE','当前必需工序/原件未齐')
        weld_ids={w.id for w in db.scalars(select(TraceWeld).where(TraceWeld.spool_id==s.id))}
        if set(b.weld_ids)!=weld_ids:fail(422,'WELD_COVERAGE','检测须覆盖本管段全部适用焊缝')
        originals(db,s,ids);data={'passed':b.passed,'reason':b.reason,'fingerprint':fingerprint(rows),'weld_ids':sorted(weld_ids)};append(db,a,s,'inspection',data,ids,b.occurred_at.isoformat() if b.occurred_at else None)
        state=(('tested' if t.pressure and pressure_valid(db,s,rows) else 'installed') if latest(rows,'installation') else 'shipped' if latest(rows,'shipment') else 'ready') if b.passed else ('hold' if latest(rows,'shipment') else 'rework')
    elif b.action in {'ship','install'}:
        expected='ready' if b.action=='ship' else 'shipped'
        if state!=expected or not quality_valid(db,s,rows):fail(409,'QUALITY_BLOCKED','须质量报告、全部焊缝及有效放行齐全，才可发运/安装')
        if not b.location or not b.reference or not b.occurred_at:fail(422,'LOCATION_REQUIRED','须填写实际位置、单据/运输依据和发生时间')
        originals(db,s,ids,False);append(db,a,s,'shipment' if b.action=='ship' else 'installation',{'location':b.location,'reference':b.reference},ids,b.occurred_at.isoformat());state='shipped' if b.action=='ship' else 'installed'
    elif b.action=='confirm_pressure':
        if state!='installed' or not t.pressure or b.passed is None or not b.reason:fail(409,'PRESSURE_STATE','须在已安装且适用试压阶段由质量明确结果')
        if not quality_valid(db,s,rows):fail(409,'QUALITY_RECHECK','返修或追溯更正后，须先重新质量检测核对')
        p=latest(effective(rows),'pressure');old=latest(rows,'pressure_result');repair=latest(rows,'repair')
        if not p:fail(409,'PRESSURE_REQUIRED','现场试压记录/报告未齐')
        if old and (old.data['record_id']==p.id or (not old.data['passed'] and (not repair or not old.received_at<repair.received_at<p.received_at))):fail(409,'REPAIR_REQUIRED','试压不合格后须先返修、再提交新的试压报告')
        originals(db,s,p.file_ids);originals(db,s,ids);append(db,a,s,'pressure_result',{'record_id':p.id,'passed':b.passed,'reason':b.reason,'fingerprint':fingerprint(rows)},ids);state='tested' if b.passed else 'installed'
    elif b.action=='complete':
        if state!=('tested' if t.pressure else 'installed') or not quality_valid(db,s,rows) or (t.pressure and not pressure_valid(db,s,rows)):fail(409,'HISTORY_INCOMPLETE','安装、适用工序、质量放行或试压确认未齐')
        if not b.reason:fail(422,'REASON_REQUIRED','请记录质量履历核对依据')
        state='completed'
    elif b.action=='scrap':
        if not b.reason:fail(422,'REASON_REQUIRED','报废须质量确认依据，编码永久保留')
        state='scrapped'
    elif b.action=='label':
        data={'locator':'/?spool='+s.id,'number':1+db.query(TraceEvent).filter(TraceEvent.spool_id==s.id,TraceEvent.action=='label').count()}
    cas(db,Spool,s,b.revision,state=state);event(store,db,a,s,b.action,rid,data or {'reason':b.reason});return {'id':s.id,'revision':s.revision}|({'locator':data['locator']} if b.action=='label' else {})

def reshape(store,db,a,pid,b,rid):
    role(store,db,a,pid,{'项目经理'})
    if len({p.id for p in b.parents})!=len(b.parents) or not ((len(b.parents)==1 and len(b.codes)>1) or (len(b.parents)>1 and len(b.codes)==1)):fail(422,'SHAPE_INVALID','拆分一件生成多件；合并多件生成一件')
    parents=[get(db,Spool,pid,p.id) for p in b.parents];first=parents[0];o=get(db,TraceOrder,pid,first.order_id)
    if a.id!=o.pm_id and not workflow_admin(store,db,a,pid):fail(403,'ASSIGNED_ONLY','仅指定项目经理可登记拆并')
    for s,p in zip(parents,b.parents):
        if s.order_id!=first.order_id or s.template_id!=first.template_id or s.state not in {'registered','fabricating','rework'}:fail(409,'SHAPE_STATE','拆并须同订单同模板且尚未发运/放行')
        require_source(db,s);cas(db,Spool,s,p.revision,state='retired');event(store,db,a,s,'reshape_parent',rid,{'reason':b.reason})
    ids=[]
    for code in b.codes:
        s=Spool(id=uid(),project_id=pid,order_id=first.order_id,template_id=first.template_id,code=code,parents=[p.id for p in parents],created_by=a.id);db.add(s);db.flush();event(store,db,a,s,'reshape_child',rid,{'reason':b.reason});ids.append(s.id)
    return {'ids':ids}
