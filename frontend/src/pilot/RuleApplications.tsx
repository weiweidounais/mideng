import {useEffect,useState,type FormEvent} from 'react';
import {mutate,request,localDate} from './client';
import {canPublishEvaluation,normalizedCases,type Evaluation,type RuleCase,type RuleHistory} from './rule-results';
import type {RuleDefinition} from './RuleCanvas';
export type RuleApp={id:string;name:string;revision:number;published:boolean;published_revision:number|null;definition:RuleDefinition|null;versions:{revision:number;published_at:string}[]};
type Operate=(work:()=>Promise<void>)=>Promise<void>;
const stepLabels:Record<string,string>={success:'成功',failed:'失败',skipped:'未执行'};

function saveReport(report:RuleHistory){
 const blob=new Blob([JSON.stringify(report,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob);
 const anchor=document.createElement('a');anchor.href=url;anchor.download='mideng-rule-'+report.id+'.json';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function ReportInput({text}:{text:string}){return text.length<=240?<span className="rule-output">{text}</span>:<div className="rule-long-input"><p>{text.slice(0,100)}…</p><details><summary>查看全部输入（{text.length}字）</summary><p>{text}</p></details></div>;}
function EvaluationDetails({report,blocked=false}:{report:Evaluation;blocked?:boolean}){return <div className="rule-evaluation" aria-label="逐条测试结果">
 <p className={report.passed===report.total?'notice success':'notice error'}>通过 {report.passed} / {report.total} 条 · 草稿 v{report.application_revision} · {localDate(report.created_at)}</p>
 <p className="fine">测试报告绑定应用和草稿版本；更改草稿或测试用例后须重新核对。未调用模型。</p>
 {report.cases.map(row=><details key={row.number} className="rule-case-result" open={!row.passed}><summary>用例 {row.number} · {row.passed?'通过':'未通过'}</summary>
  {row.steps.filter(step=>step.status==='failed').map(step=><p className="notice error" key={step.node_id}>节点“{step.label}”未完成：{step.error??'请核对输入和流程配置。'}</p>)}<dl><dt>输入</dt><dd><ReportInput text={row.input}/></dd><dt>预期</dt><dd>{stepLabels[row.expectStatus]}{row.expectContains?'，包含：'+row.expectContains:''}</dd><dt>实际</dt><dd>{stepLabels[row.actual_status]}：{row.output_preview||'无输出'}{row.truncated?'（节选）':''}</dd></dl>
  <ol className="rule-step-list">{row.steps.map(step=><li key={step.node_id}><strong>{step.label} · {stepLabels[step.status]} <small>节点 {step.node_id}</small></strong>{step.error&&<p role="alert">{step.error}</p>}{step.output_preview&&<pre>{step.output_preview}{step.truncated?'\n（节选）':''}</pre>}</li>)}</ol>
 </details>)}<details className="version-block"><summary>报告标识与定义校验</summary><p className="fine">报告：{report.id}<br/>定义SHA256：{report.definition_sha256}</p></details>
 <button className="secondary compact" disabled={blocked} onClick={()=>saveReport(report)}>下载测试报告</button>
 </div>;}

function ApplicationCard({app,path,owner,blocked,operate,onEdit,onChanged}:{app:RuleApp;path:string;owner:boolean;blocked:boolean;operate:Operate;onEdit:(app:RuleApp)=>void;onChanged:()=>void}){
 const[cases,setCases]=useState<RuleCase[]>([{input:'材料到货',expectContains:'材料到货',expectStatus:'success'}]),[report,setReport]=useState<Evaluation|null>(null),[output,setOutput]=useState(''),[runFailed,setRunFailed]=useState(false);
 const ready=canPublishEvaluation(report,app,cases),valid=cases.every(c=>c.input.trim()&&(c.expectStatus==='failed'||c.expectContains?.trim()));
 function change(index:number,field:'input'|'expectContains',value:string){setCases(list=>list.map((item,i)=>i===index?{...item,[field]:value}:item));}
 async function evaluate(e:FormEvent){e.preventDefault();if(!valid||blocked)return;setReport(null);await operate(async()=>{const result=await mutate<Evaluation>(appPath+'/evaluate','POST',{revision:app.revision,cases:normalizedCases(cases)},crypto.randomUUID());setReport(result);onChanged();});}
 const appPath=path+'/applications/'+app.id;
 async function run(e:FormEvent<HTMLFormElement>){e.preventDefault();if(blocked)return;const f=new FormData(e.currentTarget),draft=(e.nativeEvent as SubmitEvent).submitter?.getAttribute('value')==='draft'||!app.published;
  await operate(async()=>{const result=await mutate<{output:string;status:string}>(appPath+'/run','POST',{input:String(f.get('input')),mode:draft?'draft':'published'},crypto.randomUUID());setRunFailed(result.status==='failed');setOutput(result.status==='failed'?'运行未完成，请在下方本人记录中查看失败节点。':result.output);onChanged();});}
 return <article className="scheme-card rule-application-card"><div className="business-heading"><div><h3>{app.name}</h3><p>{owner&&<>当前草稿 v{app.revision} · </>}{app.published?'正在使用已发布 v'+app.published_revision:'尚未发布'}</p></div>{owner&&app.definition&&<button className="secondary compact" disabled={blocked} onClick={()=>onEdit(app)}>编辑流程与草稿</button>}</div>
  <form onSubmit={e=>void run(e)}><label>运行输入<textarea name="input" required maxLength={10000}/></label><div className="heading-actions"><button className="primary" disabled={blocked}>{app.published?'运行已发布版本':'试运行草稿'}</button>{owner&&app.published&&<button className="secondary" disabled={blocked} name="runmode" value="draft">试运行当前草稿</button>}</div></form>
  {output&&<section className={runFailed?"notice error":"notice success"} role="status"><h4>本次运行输出</h4><p className="rule-output">{output}</p></section>}
  {owner&&<><form className="rule-evaluation-form" onSubmit={e=>void evaluate(e)}><h4>发布前固定用例</h4><p className="fine">先核对实际结果，全部通过后再确认发布；目前发布版继续供同事使用。</p>{cases.map((item,index)=><fieldset key={index}><legend>用例 {index+1}</legend><label>测试输入<textarea required maxLength={2000} value={item.input} onChange={e=>change(index,'input',e.target.value)} disabled={blocked}/></label><label>预期结果应包含<input required maxLength={500} value={item.expectContains??''} onChange={e=>change(index,'expectContains',e.target.value)} disabled={blocked}/></label><button type="button" className="text-button" disabled={blocked||cases.length===1} onClick={()=>setCases(list=>list.filter((_,i)=>i!==index))}>移除此用例</button></fieldset>)}<div className="heading-actions"><button type="button" className="secondary compact" disabled={blocked||cases.length>=20} onClick={()=>setCases(list=>[...list,{input:'',expectContains:'',expectStatus:'success'}])}>＋ 添加用例</button><button className="secondary" disabled={blocked||!valid}>核对测试结果</button></div></form>
   {report&&<EvaluationDetails report={report} blocked={blocked}/>}
   <p className="fine">{ready?'当前用例已全部通过，可确认发布。':'填写并核对全部用例后，才可确认发布当前草稿。'}</p>
   <button className="primary" disabled={blocked||!ready||app.published_revision===app.revision} onClick={()=>void operate(async()=>{await mutate(appPath+'/publish','POST',{revision:app.revision,cases:normalizedCases(cases)},crypto.randomUUID());setRunFailed(false);setOutput('核对通过，已发布当前草稿。');onChanged();})}>确认发布当前草稿</button>
   {!!app.versions.length&&<details className="version-block"><summary>已发布版本与回退</summary><p className="fine">回退只切换供同事运行的发布版本，当前草稿与历史保留。</p>{app.versions.map(version=><div key={version.revision} className="rule-version"><span>v{version.revision} · {localDate(version.published_at)}{version.revision===app.published_revision?' · 正在使用':''}</span>{version.revision!==app.published_revision&&<button className="secondary compact" disabled={blocked} onClick={()=>void operate(async()=>{await mutate(appPath+'/rollback','POST',{revision:app.revision,target_revision:version.revision},crypto.randomUUID());setReport(null);setRunFailed(false);setOutput('已回退发布至 v'+version.revision+'，当前草稿保留。');onChanged();})}>回退至 v{version.revision}</button>}</div>)}</details>}
  </>}
 </article>;
}

// Keep all requests on the existing project-and-library paths.
export default function RuleApplications({apps,path,owner,blocked,operate,onEdit,onCreate,onReadError}:{apps:RuleApp[];path:string;owner:boolean;blocked:boolean;operate:Operate;onEdit:(app:RuleApp)=>void;onCreate:()=>void;onReadError:(error:unknown)=>void}){
 const[history,setHistory]=useState<RuleHistory[]>([]),[epoch,setEpoch]=useState(0),[historyLoading,setHistoryLoading]=useState(true);
 useEffect(()=>{const c=new AbortController();setHistoryLoading(true);request<RuleHistory[]>(path+'/runs',{signal:c.signal}).then(rows=>{if(!c.signal.aborted)setHistory(rows);}).catch(error=>{if(!c.signal.aborted){setHistory([]);onReadError(error);}}).finally(()=>{if(!c.signal.aborted)setHistoryLoading(false);});return()=>c.abort();},[path,epoch,onReadError]);
 const changed=()=>setEpoch(value=>value+1);
 return <><div className="business-heading">{owner&&<button className="primary" disabled={blocked} onClick={onCreate}>新建模板应用</button>}<button className="secondary compact" disabled={blocked||historyLoading} onClick={changed}>刷新本人运行记录</button></div><p className="fine">规则应用不会调用模型、修改业务记录或代替人工审批；草稿仅资料责任人可维护和试运行。</p>
 {apps.map(app=><ApplicationCard key={app.id} app={app} path={path} owner={owner} blocked={blocked} operate={operate} onEdit={onEdit} onChanged={changed}/>)}
 {!apps.length&&<p className="empty-copy">还没有可读应用；由资料责任人新建草稿、核对用例并发布。</p>}
 <section className="rule-run-history"><h3>本人运行与测试记录</h3><p className="fine">最近50条，仅当前账号可读；报告保留当时版本，更改草稿不会改写历史。</p>{historyLoading?<p role="status">正在读取记录…</p>:!history.length?<p className="empty-copy">暂无运行或测试记录。</p>:history.map(item=><details className="rule-history-entry" key={item.id}><summary>{apps.find(app=>app.id===(item.purpose==='evaluation'?item.application_id:item.applicationId))?.name??'历史应用'} · {item.purpose==='evaluation'?'用例核对 · v'+item.application_revision+' · '+item.passed+'/'+item.total:'应用运行 · '+(item.mode==='draft'?'草稿':'发布版')+' v'+item.application_revision+' · '+(stepLabels[item.status]??item.status)} · {localDate(item.purpose==='evaluation'?item.created_at:item.createdAt)}</summary>{item.purpose==='evaluation'?<EvaluationDetails report={item} blocked={blocked}/>:<><p className="rule-output">{item.output||'无输出'}</p><ol className="rule-step-list">{item.steps.map(step=><li key={step.nodeId}><strong>{step.label} · {stepLabels[step.status]??step.status} <small>节点 {step.nodeId}</small></strong>{step.error&&<p role="alert">{step.error}</p>}{step.output&&<pre>{step.output.slice(0,1000)}{step.output.length>1000?'\n（节选）':''}</pre>}</li>)}</ol><button className="secondary compact" disabled={blocked} onClick={()=>saveReport(item)}>下载运行报告</button></>}</details>)}</section>
 </>;
}
