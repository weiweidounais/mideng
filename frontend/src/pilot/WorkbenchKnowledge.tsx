import {businessRoles} from './business-permissions';
import {useEffect,useRef,useState,type FormEvent} from 'react';
import {request,type Project} from './client';
import {sections,type Section,type ViewRoute} from './navigation';

type Answer={project_id:string;query:string;mode:'keyword';model_enabled:false;keywords:string[];notice:string;
 sources:{library_id:string;library_name:string;document_id:string;name:string;location:string;content:string;truncated:boolean}[];
 entries:{section:Section;title:string;reason:string}[]};
const examples=['材料到货后怎么验收？','设计方案确定后如何采购？','知识库在哪里导入？','如何生成规则应用？'];
const duties:{role:string;section:Section;description:string}[]=[
 {role:'市场',section:'requirements',description:'提出需求'},
 {role:'设计',section:'requirements',description:'编制方案'},
 {role:'项目经理',section:'procurement',description:'提采购需求、复核'},
 {role:'采购',section:'procurement',description:'下单与到货协作'},
 {role:'质量',section:'procurement',description:'材料验收、质量协作'},
 {role:'商务',section:'requirements',description:'发起需求、发布与合同成本归档'},
 {role:'工厂',section:'trace',description:'生产与预制'},
 {role:'现场',section:'trace',description:'施工与安装'},
 {role:'财务',section:'cost',description:'成本与月结'},
 {role:'管理员',section:'requirements',description:'成员与岗位授权'},
];

export default function WorkbenchKnowledge({project,onNavigate}:{project?:Project;onNavigate:(route:ViewRoute)=>void}){
 const [question,setQuestion]=useState(''),[answer,setAnswer]=useState<Answer|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const inFlight=useRef<AbortController|null>(null);
 useEffect(()=>()=>inFlight.current?.abort(),[]);
 function go(section:Section){if(project)onNavigate({project:project.id,section});}
 async function ask(e:FormEvent<HTMLFormElement>){
  e.preventDefault();if(!project||!question.trim()||busy)return;
  const controller=new AbortController();inFlight.current=controller;setBusy(true);setError('');setAnswer(null);
  try{
   const result=await request<Answer>('/projects/'+project.id+'/workspace/ask',{method:'POST',body:JSON.stringify({query:question.trim()}),signal:controller.signal});
   if(!controller.signal.aborted)setAnswer(result);
  }catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:'读取未完成，请重试。');}
  finally{if(!controller.signal.aborted){setBusy(false);inFlight.current=null;}}
 }
 return <>
  <section className="knowledge-home panel" aria-labelledby="knowledge-home-title">
   <span className="eyebrow">探索知识 · 连接业务</span>
   <h2 id="knowledge-home-title">先问一个问题，找到依据和下一步</h2>
   <p>查询当前项目可读的已发布知识，从回答进入相关业务。</p>
   <form onSubmit={e=>void ask(e)} className="workbench-question-form">
    <label htmlFor="workbench-question">你想了解或办理什么？</label>
    <textarea id="workbench-question" rows={3} maxLength={1000} required value={question} disabled={!project||busy}
     placeholder="例如：材料到货后，谁来验收？从哪里继续采购流程？" onChange={e=>setQuestion(e.target.value)}/>
    <div className="question-form-footer"><span>本地原文检索 · 未启用AI生成</span><button className="primary" disabled={!project||busy||!question.trim()}>{busy?'正在查找依据…':'提问 →'}</button></div>
   </form>
   <div className="question-examples" aria-label="示例问题">{examples.map(text=><button type="button" key={text} disabled={!project||busy} onClick={()=>{setQuestion(text);document.getElementById('workbench-question')?.focus();}}>{text}</button>)}</div>
   {!project&&<p className="notice">还没有可访问项目。请先创建项目或联系管理员配置项目成员，再导入并发布知识资料。</p>}
   {busy&&<p role="status">正在当前项目的授权范围内查找原文和业务入口…</p>}
   {error&&<p className="notice error" role="alert">{error} 当前回答已清空，请核对项目授权后重试。</p>}
   {answer&&<div className="workbench-answer" aria-live="polite">
    <div className="asked-question"><span>你的问题</span><p>{answer.query}</p></div>
    <div className="answer-heading"><strong>相关依据与业务入口</strong><span className="pill">原文检索</span></div>
    <p>{answer.notice}</p>
    <div className="answer-sources">{answer.sources.map((source,index)=><article className="answer-source" key={source.document_id+':'+index}>
     <small>来源 {index+1} · {source.library_name} / {source.name} · {source.location}</small>
     <blockquote>{source.content}</blockquote>{source.truncated&&<small>此处仅显示原文节选，完整内容请进入知识空间核对。</small>}
     <button className="text-button" onClick={()=>onNavigate({project:answer.project_id,section:'knowledge',object:source.library_id,kind:'library'})}>核对来源资料 →</button>
    </article>)}</div>
    <div className="answer-business" aria-label="回答中的业务入口">{answer.entries.map(entry=><button className="secondary" key={entry.section} title={entry.reason} onClick={()=>go(entry.section)}>{entry.title} →</button>)}
     {!answer.entries.length&&<button className="secondary" onClick={()=>go('knowledge')}>进入项目知识与应用 →</button>}</div>
   </div>}
  </section>
  <section className="panel department-entrances" aria-labelledby="department-title">
   <div className="section-heading"><div><h2 id="department-title">部门与岗位协作</h2><p>按项目岗位展示职责；独立部门组织树尚未配置，操作权限以本人授权为准。</p></div>
    <button className="text-button" disabled={!project} onClick={()=>project&&onNavigate({project:project.id,section:'requirements',panel:'members'})}>查看成员与岗位配置 →</button></div>
   <div className="duty-grid">{duties.map(duty=>{
    const mine=project?.roles.includes(duty.role),disabled=!project||(duty.role==='财务'&&!businessRoles(project.roles).some(role=>['财务','项目经理'].includes(role)));
    return <button key={duty.role} className={'duty-card'+(mine?' my-duty':'')} disabled={disabled} onClick={()=>duty.role==='管理员'?project&&onNavigate({project:project.id,section:'requirements',panel:'members'}):duty.role==='市场'||duty.role==='商务'?project&&onNavigate({project:project.id,section:'requirements',desk:duty.role==='市场'?'market':'commerce'}):go(duty.section)}>
     <strong>{duty.role}{mine&&<span>本人岗位</span>}</strong><small>{duty.description}</small><span>{disabled&&project?'需财务或项目经理授权':'查看协作入口 →'}</span>
    </button>;
   })}</div>
  </section>
  <section className="panel" aria-labelledby="all-business-title"><div className="section-heading"><div><h2 id="all-business-title">全部业务入口</h2><p>原有业务节点均保留，也可以直接进入。</p></div></div>
   <div className="all-business-links">{Object.entries(sections).map(([key,label])=><button className="secondary" key={key} disabled={!project||(key==='cost'&&!businessRoles(project.roles).some(role=>['财务','项目经理'].includes(role)))} onClick={()=>go(key as Section)}>{label} →</button>)}<button className="secondary" disabled={!project} onClick={()=>project&&onNavigate({project:project.id,section:'knowledge',tab:'applications'})}>应用生成 / 规则应用 →</button></div>
  </section>
 </>;
}
