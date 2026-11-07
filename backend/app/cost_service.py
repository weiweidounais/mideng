from .pilot_service import business_roles
import copy,hashlib,json,re,calendar
from pathlib import Path
from decimal import Decimal
from datetime import datetime,date,timedelta,timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from .pilot_models import Project,Account,utcnow
from .pilot_service import uid,fail
from .handoff_service import get,cas,notify,file_view
from .cost_models import CostProfile,CostSource,CostBatch,CostLine,CostBatchLine,CostBook,CostBudget,CostCalendar,CostClose,CostSnapshot,CostEvent
from .cost_import import FIELDS,REQUIRED,KINDS,parse

def finance(store,db,a,pid):return store.membership(db,a,pid,'cost.detail')
def money(v):
 if not re.fullmatch(r'-?\d{1,14}(\.\d{1,2})?',str(v)):raise ValueError('金额须为最多2位小数的确定数值')
 return Decimal(str(v)).quantize(Decimal('.01'))
def amount(v):return format(v.quantize(Decimal('.01')),'f')
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def linehash(v):return digest({k:x for k,x in v.items() if k not in {'row','profile_id'}})
def identity(v):return (v['source_system'],v['source_key'],v['period'],v['line_version'])
def original(f):
 p=Path(f.path)
 if not p.is_file():fail(409,'ORIGINAL_MISSING','财务来源原件缺失')
 data=p.read_bytes()
 if hashlib.sha256(data).hexdigest()!=f.sha256:fail(409,'ORIGINAL_CHANGED','财务原件哈希不符')
 return data

def files(db,pid,ids):
 if not ids:fail(422,'EVIDENCE_REQUIRED','请关联已经上传的确认依据原件')
 for fid in ids:original(get(db,CostSource,pid,fid))
def generation(db,pid):
 book=db.get(CostBook,pid);return book.revision if book else 0
def bump(db,pid):
 b=db.get(CostBook,pid)
 if b:b.revision+=1
 else:db.add(CostBook(project_id=pid,revision=1))
 db.flush()
def event(store,db,a,pid,oid,action,rid,body=None):
 store.audit(db,a,'cost.'+action,oid,1,rid,pid);db.add(CostEvent(id=uid(),project_id=pid,object_id=oid,action=action,body=body or {},actor_id=a.id))
def active_batches(db,pid):return list(db.scalars(select(CostBatch).where(CostBatch.project_id==pid,CostBatch.state=='committed')))
def ledger(db,pid,exclude=()):
 q=select(CostLine).join(CostBatchLine,CostBatchLine.line_id==CostLine.id).join(CostBatch,CostBatch.id==CostBatchLine.batch_id).where(CostLine.project_id==pid,CostBatch.project_id==pid,CostBatch.state=='committed')
 if exclude:q=q.where(CostBatch.id.not_in(exclude))
 return list(db.scalars(q).unique())
def error(row,field,value,message):return {'row':row,'field':field,'value':str(value)[:200],'reason':message}
def normalize(db,b):
 profile=get(db,CostProfile,b.project_id,b.profile_id);p=db.get(Project,b.project_id);cfg=profile.body;errors=[];lines=[];seen=set();meta=b.meta
 for raw in b.rows:
  n=raw['row'];v={k:raw['values'].get(b.mapping.get(k,''),'').strip() for k in FIELDS};before=len(errors)
  for h in raw['formulas']:errors.append(error(n,h,raw['values'].get(h,''),'公式不执行，请提供确定数值'))
  needed=REQUIRED|({'source_id'} if cfg['key_mode']=='id' else set(cfg['key_fields']))
  for k in needed:
   if not v.get(k):errors.append(error(n,FIELDS[k],v.get(k,''),'必填值缺失，不按0处理'))
  if any(len(x)>2000 for x in v.values()):errors.append(error(n,'单元格','','超过2000字符'))
  if v.get('project_code')!=p.code:errors.append(error(n,'项目编码',v.get('project_code',''),'与当前授权项目不一致'))
  if v.get('currency')!=meta['currency'] or v.get('tax_basis')!=meta['tax_basis']:errors.append(error(n,'币种/税口径',v.get('currency','')+'/'+v.get('tax_basis',''),'不允许在一批中混合口径或自动换算'))
  dt=None
  try:
   dt=date.fromisoformat(v.get('entry_date','')[:10]);cut=datetime.fromisoformat(meta['data_cutoff']).astimezone(ZoneInfo('Asia/Shanghai')).date()
   if dt.strftime('%Y-%m')!=meta['period'] or dt>cut:raise ValueError()
  except ValueError:errors.append(error(n,'凭证日期',v.get('entry_date',''),'须为本期间日期，且不晚于源数据截止'))
  subject=cfg['subjects'].get(v.get('subject_code',''));wbs=cfg['wbs'].get(v.get('wbs_code',''))
  if not subject:errors.append(error(n,'原科目',v.get('subject_code',''),'未映射，保留待处理，不进入正式合计'))
  if not wbs:errors.append(error(n,'原WBS',v.get('wbs_code',''),'未映射，保留待处理，不进入正式合计'))
  kind=KINDS.get(v.get('kind',''),v.get('kind',''))
  if kind not in set(KINDS.values()):errors.append(error(n,'类型',kind,'须明确实际/暂估/承诺/付款/发票/待分摊/冲正'))
  try:
   val=money(v.get('amount',''))
   if (kind=='reversal' and val>=0) or (kind!='reversal' and val<0):raise ValueError('负数仅用于明确关联的冲正')
  except ValueError as e:errors.append(error(n,'金额',v.get('amount',''),str(e)));val=Decimal(0)
  try:
   q=v.get('quantity','')
   if not re.fullmatch(r'-?\d{1,12}(\.\d{1,6})?',q):raise ValueError()
   qty=Decimal(q)
   if qty==0 or (qty<0)!=(kind=='reversal'):raise ValueError()
  except ValueError:errors.append(error(n,'数量',v.get('quantity',''),'须为确定数量，冲正为负，其余为正'));qty=Decimal(0)
  if cfg['key_mode']=='id':key=v.get('source_id','')
  else:key='combo:'+digest([v.get(k,'') for k in cfg['key_fields']])
  related=[v.get(k,'') for k in ['related_source','related_period','related_id','related_version']]
  if (kind=='reversal' or any(related)) and not all(related):errors.append(error(n,'冲正/替代关联','/'.join(related),'须明确原源系统、期间、源ID及行版本'))
  line={**v,'quantity':format(qty.normalize(),'f'),'entry_date':dt.isoformat() if dt else v.get('entry_date',''),'source_system':profile.source_system,'source_key':key,'line_version':v.get('line_version',''),'period':meta['period'],'currency':meta['currency'],'tax_basis':meta['tax_basis'],'kind':kind,'amount':amount(val),'subject':subject,'wbs':wbs,'estimate_policy':cfg['estimate_policy'],'related':[related[0],related[2],related[1],related[3]] if all(related) else None,'row':n,'profile_id':profile.id}
  ident=identity(line)
  if ident in seen:errors.append(error(n,'源键/行版本',key,'批内重复或组合键有歧义，不能猜测合并'))
  seen.add(ident)
  if len(errors)==before:lines.append(line)
 return lines,errors

def validate_set(bodies):
 lookup={identity(v):v for v in bodies};errors=[];versions={};reversed_totals={};estimates={};actuals={}
 for v in bodies:
  base=(v['source_system'],v['source_key'],v['period']);versions.setdefault(base,set()).add(v['line_version'])
  if len(versions[base])>1:errors.append(error(v.get('row',0),'源ID',v['source_key'],'有效集合存在多个行版；累计表须显式替换旧批次范围'))
  if v['kind']=='reversal':
   target=lookup.get(tuple(v['related'] or []))
   if not target or target['kind']=='reversal' or identity(target)==identity(v):errors.append(error(v.get('row',0),'冲正关联',v['source_key'],'原行不存在/已撤回或关联无效'));continue
   if any(v.get(k)!=target.get(k) for k in ['currency','tax_basis','unit','business_id']):errors.append(error(v.get('row',0),'冲正口径',v['source_key'],'币种/税/单位/事项须与原行一致'))
   k=identity(target);reversed_totals[k]=reversed_totals.get(k,Decimal(0))-money(v['amount'])
   if reversed_totals[k]>money(target['amount']):errors.append(error(v.get('row',0),'冲正金额',v['amount'],'累计冲正不能超过原行金额'))
 for v in bodies:
  net=money(v['amount'])-reversed_totals.get(identity(v),Decimal(0));business=(v.get('business_id'),v['currency'],v['tax_basis'])
  if v['kind']=='estimate':estimates[business]=estimates.get(business,Decimal(0))+net
  if v['kind']=='actual':actuals[business]=actuals.get(business,Decimal(0))+net
  if v['kind']=='actual' and v.get('related'):
   target=lookup.get(tuple(v['related']))
   if not target or target['kind']!='estimate' or any(target[k]!=v[k] for k in ['business_id','currency','tax_basis']):errors.append(error(v.get('row',0),'实际替代关联',v['source_key'],'实际替代须关联同事项原暂估行'))
 for key,est in estimates.items():
  if est>0 and actuals.get(key,Decimal(0))>0:errors.append(error(0,'暂估/实际',key[0],'同事项暂估未完整冲正，不能重复确认实际'))
 return errors

def precheck(db,b):
 new,errors=normalize(db,b);old=ledger(db,b.project_id);targets=b.meta['replace_ids'] if b.meta['mode']=='replace' else []
 for bid in targets:
  target=get(db,CostBatch,b.project_id,bid);tp=get(db,CostProfile,b.project_id,target.profile_id);profile=get(db,CostProfile,b.project_id,b.profile_id)
  if target.state!='committed' or tp.source_system!=profile.source_system or any(target.meta[k]!=b.meta[k] for k in ['period','currency','tax_basis']):errors.append(error(0,'替换范围',bid,'须是同项目/期间/来源/币种/税的有效旧批次'))
 known={identity(l.body):l for l in db.scalars(select(CostLine).where(CostLine.project_id==b.project_id))};duplicates=0
 for v in new:
  previous=known.get(identity(v))
  if previous:
   if previous.digest!=linehash(v):errors.append(error(v['row'],'行版本',v['line_version'],'同源ID/期间/行版本内容不同，须新行版或明确冲正'))
   else:duplicates+=1
 projected={identity(l.body):l.body for l in ledger(db,b.project_id,targets)}
 projected.update({identity(v):v for v in new});errors+=validate_set(list(projected.values()))
 totals=lambda vs:{kind:amount(sum((money(v['amount']) for v in vs if v['kind']==kind),Decimal(0))) for kind in KINDS.values()}
 return new,errors[:1000],{'rows':len(b.rows),'new_rows':len(new)-duplicates,'duplicate_rows':duplicates,'error_count':len(errors),'replace_ids':targets,'before':totals([l.body for l in old if l.period==b.meta['period'] and l.body['currency']==b.meta['currency'] and l.body['tax_basis']==b.meta['tax_basis']]),'after':totals([v for v in projected.values() if all(v[k]==b.meta[k] for k in ['period','currency','tax_basis'])])},generation(db,b.project_id)

def run_job(store):
 now=utcnow();claim=uid()
 with store.transaction(write=True) as db:
  candidates=list(db.scalars(select(CostBatch).where(CostBatch.state.in_(['queued_parse','queued_check','running_parse','running_check'])).order_by(CostBatch.at)))
  b=next((x for x in candidates if x.state.startswith('queued_') or not x.lease_until or x.lease_until<=now),None)
  if not b:return False
  if b.attempts>=3:
   b.state='invalid';b.errors=[error(0,'后台任务','','重试次数已达3次，请核对原件后人工重试')];b.revision+=1;return True
  op=b.state.split('_')[1];bid=b.id;b.state='running_'+op;b.claim_id=claim;b.lease_until=(datetime.now(timezone.utc)+timedelta(seconds=10)).isoformat();b.attempts+=1;b.revision+=1
 try:
  with store.transaction() as db:
   b=db.get(CostBatch,bid);source=get(db,CostSource,b.project_id,b.source_id);data=original(source)
   if op=='parse':headers,rows=parse(data,source.name);result={'columns':headers,'rows':rows,'state':'mapping','errors':[]}
   else:
    norm,errors,differences,gen=precheck(db,b);result={'normalized':norm,'errors':errors,'differences':differences,'checked_generation':gen,'state':'invalid' if errors else 'ready'}
 except Exception as e:
  message=e.detail.get('message','解析/预检失败') if hasattr(e,'detail') and isinstance(e.detail,dict) else '后台解析/预检失败，请核对原件并重试'
  result={'state':'invalid','errors':[error(0,'文件','',message)]}
 with store.transaction(write=True) as db:
  b=db.get(CostBatch,bid)
  if b.claim_id!=claim:return False
  for k,v in result.items():setattr(b,k,v)
  b.claim_id=None;b.lease_until=None;b.updated_at=utcnow();b.revision+=1
  notify(db,b.project_id,[b.actor_id],'成本导入'+('预检通过，待财务确认' if b.state=='ready' else '请核对列映射' if b.state=='mapping' else '存在待处理错误'),'cost_batch',b.id)
 return True

def profile(store,db,a,pid,b,rid):
 finance(store,db,a,pid);prior=list(db.scalars(select(CostProfile).where(CostProfile.project_id==pid,CostProfile.source_system==b.source_system)));p=CostProfile(id=uid(),project_id=pid,source_system=b.source_system,number=max([x.number for x in prior],default=0)+1,body=b.model_dump(mode='json'),actor_id=a.id);db.add(p);db.flush();event(store,db,a,pid,p.id,'profile',rid);return {'id':p.id,'revision':1}
def calendar_create(store,db,a,pid,b,rid):
 finance(store,db,a,pid);c=CostCalendar(id=uid(),project_id=pid,body=b.model_dump(mode='json'),actor_id=a.id);db.add(c);db.flush();event(store,db,a,pid,c.id,'calendar',rid);return {'id':c.id,'revision':1}
def budget(store,db,a,pid,b,rid):
 finance(store,db,a,pid);files(db,pid,b.file_ids);existing=[x for x in db.scalars(select(CostBudget).where(CostBudget.project_id==pid)) if x.body['currency']==b.currency and x.body['tax_basis']==b.tax_basis]
 if b.kind=='baseline' and any(x.body['kind']=='baseline' for x in existing):fail(409,'BASELINE_EXISTS','原预算基线已冻结，后续批准调整单独追加')
 if b.kind=='adjustment' and not any(x.body['kind']=='baseline' for x in existing):fail(422,'BASELINE_REQUIRED','先登记业务确认的原预算基线')
 if b.change_id:
  from .change_models import ChangeCase,ChangeVersion
  c=get(db,ChangeCase,pid,b.change_id)
  if not c.current_version_id:fail(422,'CHANGE_APPROVAL','关联变更须有已发布批准依据')
  from .change_service import valid_files
  v=get(db,ChangeVersion,pid,c.current_version_id);valid_files(db,c,v.body['approval']['file_ids'],'approval')
 row=CostBudget(id=uid(),project_id=pid,body=b.model_dump(mode='json')|{'amount':amount(money(b.amount))},actor_id=a.id);db.add(row);db.flush();bump(db,pid);event(store,db,a,pid,row.id,'budget',rid);return {'id':row.id,'revision':1}

def batch_view(b):return {k:getattr(b,k) for k in ['id','revision','state','meta','profile_id','source_id','columns','mapping','errors','differences','rows','normalized','actor_id','confirmed_by']}
def batch_action(store,db,a,b,body,rid):
 finance(store,db,a,b.project_id)
 if body.action=='mapping':
  if b.state not in {'mapping','invalid','ready'}:fail(409,'BATCH_STATE','后台解析完成后再确认映射')
  p=get(db,CostProfile,b.project_id,b.profile_id);needed=REQUIRED|({'source_id'} if p.body['key_mode']=='id' else set(p.body['key_fields']))
  if set(body.mapping)-set(FIELDS) or not needed<=set(body.mapping) or any(h not in b.columns for h in body.mapping.values()):fail(422,'MAPPING_REQUIRED','请完整映射必填列，并从实际表头选择')
  cas(db,CostBatch,b,body.revision,mapping=body.mapping,state='queued_check',errors=[],attempts=0,claim_id=None,lease_until=None)
 elif body.action=='recheck':
  if b.state not in {'invalid','ready','mapping'}:fail(409,'BATCH_STATE','当前批次不能重试')
  cas(db,CostBatch,b,body.revision,state='queued_check' if b.mapping else 'queued_parse',errors=[],attempts=0,claim_id=None,lease_until=None)
 elif body.action=='commit':
  if b.state!='ready' or not body.confirmed or not body.reason:fail(409,'FINANCE_CONFIRM','须预检通过并由财务明确核对确认')
  if b.checked_generation!=generation(db,b.project_id):fail(409,'LEDGER_CHANGED','预检后账本发生变化，请重新预检')
  original(get(db,CostSource,b.project_id,b.source_id));new,errors,_,_=precheck(db,b)
  if errors:fail(409,'PRECHECK_CHANGED','来源或冲正/替换关系已变化，须重新预检')
  for v in new:
   ident=identity(v);old=db.scalar(select(CostLine).where(CostLine.project_id==b.project_id,CostLine.source_system==ident[0],CostLine.source_key==ident[1],CostLine.period==ident[2],CostLine.line_version==ident[3]))
   if not old:
    old=CostLine(id=uid(),project_id=b.project_id,source_system=ident[0],source_key=ident[1],period=ident[2],line_version=ident[3],digest=linehash(v),body={k:x for k,x in v.items() if k!='row'});db.add(old);db.flush()
   db.add(CostBatchLine(batch_id=b.id,line_id=old.id))
  for bid in b.meta['replace_ids']:
   prior=get(db,CostBatch,b.project_id,bid);cas(db,CostBatch,prior,prior.revision,state='replaced');event(store,db,a,b.project_id,bid,'replaced',rid,{'by':b.id,'reason':body.reason})
  cas(db,CostBatch,b,body.revision,state='committed',confirmed_by=a.id);bump(db,b.project_id)
 elif body.action=='withdraw':
  if not body.reason or b.state in {'replaced','withdrawn'}:fail(409,'WITHDRAW_REASON','撤回须明确理由，已被替换/撤回不可重复撤回')
  if b.state=='committed' and validate_set([l.body for l in ledger(db,b.project_id,[b.id])]):fail(409,'LINKED_REVERSAL','撤回会破坏有效冲正链，请先核对关联批次')
  cas(db,CostBatch,b,body.revision,state='withdrawn',claim_id=None,lease_until=None);bump(db,b.project_id)
 event(store,db,a,b.project_id,b.id,body.action,rid,{'reason':body.reason});return {'id':b.id,'revision':b.revision}

def due_at(period,cal):
 if not cal:return None
 year,month=map(int,period.split('-'));d=date(year,month,calendar.monthrange(year,month)[1])+timedelta(days=1);body=cal.body;start=date.fromisoformat(body['start']);end=date.fromisoformat(body['end']);days=set(body['workdays']);count=0
 while d<=end:
  if d<start:return None
  if d.isoformat() in days:
   count+=1
   if count==3:return datetime.combine(d,datetime.max.time().replace(microsecond=0),tzinfo=ZoneInfo('Asia/Shanghai')).astimezone(timezone.utc).isoformat()
  if d==end:break
  d+=timedelta(days=1)
 return None

def calculate(db,pid,inputs):
 all_lines=[l.body|{'id':l.id} for l in ledger(db,pid)];lookup={identity(v):v for v in all_lines};scope=lambda v:v['period']==inputs['period'] and v['currency']==inputs['currency'] and v['tax_basis']==inputs['tax_basis'];selected=[v for v in all_lines if scope(v)];totals={k:Decimal(0) for k in ['actual','estimate','commitment','payment','invoice','unallocated']};included=Decimal(0)
 for v in selected:
  target=lookup.get(tuple(v['related'])) if v['kind']=='reversal' else v
  if not target:continue
  kind=target['kind'];totals[kind]+=money(v['amount'])
  if kind=='estimate' and target['estimate_policy']=='include':included+=money(v['amount'])
 budgets=[b for b in db.scalars(select(CostBudget).where(CostBudget.project_id==pid)) if b.body['currency']==inputs['currency'] and b.body['tax_basis']==inputs['tax_basis']];baseline=next((b for b in budgets if b.body['kind']=='baseline'),None);original_budget=money(baseline.body['amount']) if baseline else None;adjustments=sum((money(b.body['amount']) for b in budgets if b.body['kind']=='adjustment'),Decimal(0));current=original_budget+adjustments if baseline else None;reported=totals['actual']+included
 batches=[b for b in active_batches(db,pid) if all(b.meta[k]==inputs[k] for k in ['period','currency','tax_basis'])];open_batches=[b.id for b in db.scalars(select(CostBatch).where(CostBatch.project_id==pid)) if b.state not in {'committed','withdrawn','replaced'} and all(b.meta[k]==inputs[k] for k in ['period','currency','tax_basis'])];gaps=[]
 if not batches:gaps.append('没有经财务确认的来源批次，不能把缺数据当0')
 if open_batches:gaps.append('仍有未处理导入批次')
 if not baseline:gaps.append('原预算基线未确认')
 cal=get(db,CostCalendar,pid,inputs['calendar_id']) if inputs.get('calendar_id') else None;deadline=due_at(inputs['period'],cal)
 if not deadline:gaps.append('月结时限未配置或公司日历覆盖不足')
 control=money(inputs['control_total']) if inputs.get('control_total') is not None else None
 if control is not None and (not inputs.get('control_basis') or totals['actual']+totals['unallocated']!=control):gaps.append('实际加待分摊与控制总额不平，或缺控制范围依据')
 partial=control is None or totals['unallocated']!=0
 if partial and (not inputs.get('allow_partial') or not inputs.get('partial_reason')):gaps.append('范围未知/待分摊须明确标部分归集并说明，不得宣称完整')
 revenue=None
 if inputs.get('revenue') is not None:
  if not inputs.get('revenue_comparable') or not inputs.get('revenue_basis') or not inputs.get('revenue_file_ids'):gaps.append('收入须确认同币种同税口径及原件依据')
  else:revenue=money(inputs['revenue'])
 actual_known=any(v['kind'] in {'actual','unallocated'} or (v['kind']=='reversal' and lookup.get(tuple(v['related']),{}).get('kind')=='actual') for v in selected) or (control==0 and bool(inputs.get('control_basis')))
 reported_known=actual_known or included!=0
 body={k:inputs[k] for k in ['period','currency','tax_basis']};body|={'original_budget':amount(original_budget) if original_budget is not None else None,'approved_adjustments':amount(adjustments),'current_budget':amount(current) if current is not None else None,'actual_accounting':amount(totals['actual']) if actual_known else None,'estimate':amount(totals['estimate']),'actual_reported':amount(reported) if reported_known else None,'estimate_included':amount(included),'commitment':amount(totals['commitment']),'payment':amount(totals['payment']),'invoice':amount(totals['invoice']),'unallocated':amount(totals['unallocated']),'variance':amount(reported-current) if current is not None and reported_known else None,'variance_rate':format((reported-current)/current,'f') if current not in {None,Decimal(0)} and reported_known else None,'revenue':amount(revenue) if revenue is not None else None,'gross_margin':amount(revenue-reported) if revenue is not None and reported_known else None,'control_total':amount(control) if control is not None else None,'completeness':format(totals['actual']/control,'f') if control not in {None,Decimal(0)} else None,'coverage':'部分/待补' if partial else '已按确认控制范围核对','control_basis':inputs.get('control_basis',''),'partial_reason':inputs.get('partial_reason',''),'calendar_id':cal.id if cal else None,'calendar_name':cal.body['name'] if cal else None,'deadline':deadline,'data_cutoff':min((b.meta['data_cutoff'] for b in batches),default=None),'batches':[b.id for b in batches],'budget_ids':[b.id for b in budgets],'line_ids':[v['id'] for v in selected],'open_batches':open_batches,'gaps':gaps,'ledger_digest':digest([[b.id for b in batches],[b.id for b in budgets],[v['id'] for v in selected]])}
 return body

def snapshot_files(db,pid,inputs,body):
 for bid in body['batches']:original(get(db,CostSource,pid,get(db,CostBatch,pid,bid).source_id))
 for bid in body['budget_ids']:files(db,pid,get(db,CostBudget,pid,bid).body['file_ids'])
 if inputs.get('revenue_file_ids'):files(db,pid,inputs['revenue_file_ids'])
def close_create(store,db,a,pid,b,rid):
 finance(store,db,a,pid);inputs=b.model_dump(mode='json');body=calculate(db,pid,inputs)
 latest=latest_snapshot(db,pid,inputs)
 if (latest.id if latest else None)!=b.correction_of:fail(409,'SNAPSHOT_CURRENT','更正须明确关联本期间同币种税口径的最新发布版')
 c=CostClose(id=uid(),project_id=pid,inputs=inputs,body=body,generation=generation(db,pid),actor_id=a.id);db.add(c);db.flush();event(store,db,a,pid,c.id,'close.draft',rid);return {'id':c.id,'revision':1}
def latest_snapshot(db,pid,scope):return db.scalar(select(CostSnapshot).where(CostSnapshot.project_id==pid,CostSnapshot.period==scope['period'],CostSnapshot.currency==scope['currency'],CostSnapshot.tax_basis==scope['tax_basis']).order_by(CostSnapshot.number.desc()))
def close_action(store,db,a,c,b,rid):
 finance(store,db,a,c.project_id)
 if c.state not in {'draft','review'}:fail(409,'CLOSE_STATE','已发布正文不可覆盖，请起更正版')
 values={}
 if b.action=='refresh':
  inputs=b.replacement.model_dump(mode='json') if b.replacement else c.inputs
  if any(inputs[k]!=c.inputs[k] for k in ['period','currency','tax_basis','correction_of']):fail(422,'CLOSE_SCOPE','草稿范围不变，更换期间请新建')
  values={'inputs':inputs,'body':calculate(db,c.project_id,inputs),'generation':generation(db,c.project_id),'state':'draft'}
 elif b.action=='cancel':
  if not b.reason:fail(422,'REASON_REQUIRED','取消草稿须说明原因')
  values={'state':'cancelled'}
 else:
  if c.generation!=generation(db,c.project_id):fail(409,'CLOSE_STALE','账本或预算已变，请刷新并重新核对草稿')
  if calculate(db,c.project_id,c.inputs)!=c.body:fail(409,'CLOSE_STALE','草稿后导入范围或待处理批次已变化，请重新核对')
  if c.body['gaps']:fail(409,'CLOSE_GAPS','月结缺项：'+'；'.join(c.body['gaps']))
  snapshot_files(db,c.project_id,c.inputs,c.body)
  if b.action=='submit_review':values={'state':'review'}
  elif b.action=='publish':
   if c.state!='review' or not b.confirmed or not b.reason:fail(409,'FINANCE_CONFIRM','须待财务确认状态，明确勾选并填写发布依据')
   prior=latest_snapshot(db,c.project_id,c.inputs)
   if (prior.id if prior else None)!=c.inputs.get('correction_of'):fail(409,'SNAPSHOT_CURRENT','已有新的发布版，须重新核对更正来源')
   publication=CostSnapshot(id=uid(),project_id=c.project_id,close_id=c.id,period=c.inputs['period'],currency=c.inputs['currency'],tax_basis=c.inputs['tax_basis'],number=(prior.number+1 if prior else 1),previous_id=prior.id if prior else None,body=copy.deepcopy(c.body)|{'finance_reason':b.reason,'correction_reason':c.inputs['reason'],'on_time':datetime.fromisoformat(utcnow())<=datetime.fromisoformat(c.body['deadline']),'rule_version':'F6-v1','diff':{k:{'before':prior.body.get(k),'after':v} for k,v in c.body.items() if prior and prior.body.get(k)!=v}},actor_id=a.id);db.add(publication);db.flush();values={'state':'published','publication_id':publication.id}
   if prior:
    old=db.get(CostClose,prior.close_id);cas(db,CostClose,old,old.revision,state='corrected')
   from .pilot_models import Membership
   recipients=[m.account_id for m in db.scalars(select(Membership).where(Membership.project_id==c.project_id)) if m.active and '项目经理' in business_roles(m.roles)]
   notify(db,c.project_id,recipients,'财务月结快照已发布：'+c.inputs['period'],'cost_snapshot',publication.id)
 cas(db,CostClose,c,b.revision,**values);event(store,db,a,c.project_id,c.id,'close.'+b.action,rid,{'reason':b.reason});return {'id':c.id,'revision':c.revision}

PUBLIC=['period','currency','tax_basis','original_budget','approved_adjustments','current_budget','actual_accounting','estimate','actual_reported','estimate_included','commitment','payment','invoice','unallocated','variance','variance_rate','revenue','gross_margin','control_total','completeness','coverage','deadline','calendar_name','data_cutoff','on_time','rule_version']
def board(store,db,a,pid):
 _,member=store.membership(db,a,pid);fin='财务' in business_roles(member.roles);pm='项目经理' in business_roles(member.roles);result={'can_finance':fin,'can_summary':fin or pm,'profiles':[],'calendars':[],'budgets':[],'files':[],'batches':[],'closes':[],'snapshots':[],'changes':[]}
 if fin:
  result['profiles']=[dict(id=p.id,number=p.number,body=p.body,actor_id=p.actor_id,at=p.at) for p in db.scalars(select(CostProfile).where(CostProfile.project_id==pid))];result['calendars']=[dict(id=p.id,body=p.body,actor_id=p.actor_id,at=p.at) for p in db.scalars(select(CostCalendar).where(CostCalendar.project_id==pid))];result['budgets']=[dict(id=p.id,body=p.body,actor_id=p.actor_id,at=p.at) for p in db.scalars(select(CostBudget).where(CostBudget.project_id==pid))];result['files']=[file_view(f) for f in db.scalars(select(CostSource).where(CostSource.project_id==pid))];result['batches']=[batch_view(b) for b in db.scalars(select(CostBatch).where(CostBatch.project_id==pid).order_by(CostBatch.at.desc()))];result['closes']=[dict(id=c.id,revision=c.revision,state=c.state,inputs=c.inputs,body=c.body,publication_id=c.publication_id) for c in db.scalars(select(CostClose).where(CostClose.project_id==pid).order_by(CostClose.at.desc()))]
  from .change_models import ChangeCase
  result['changes']=[dict(id=c.id,title=c.draft['title']) for c in db.scalars(select(ChangeCase).where(ChangeCase.project_id==pid,ChangeCase.current_version_id.is_not(None))) if c.state!='cancelled']
 if fin or pm:
  for s in db.scalars(select(CostSnapshot).where(CostSnapshot.project_id==pid).order_by(CostSnapshot.at.desc())):
   latest=latest_snapshot(db,pid,{'period':s.period,'currency':s.currency,'tax_basis':s.tax_basis});body=s.body if fin else {k:s.body.get(k) for k in PUBLIC};result['snapshots'].append(dict(id=s.id,number=s.number,previous_id=s.previous_id,body=body,actor_id=s.actor_id,at=s.at,is_current=s.id==latest.id))
 return result
