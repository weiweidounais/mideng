import {useCallback,useEffect,useMemo,useState} from 'react';
import {Alert,Button,Drawer,Empty,Input,Select,Space,Table,Tabs,Tag,message} from 'antd';
import {Activity,Bot,ChevronRight,Coins,Database,MessageSquare,Radar,Search,ThumbsDown,ThumbsUp,Workflow} from 'lucide-react';
import {api,json,ApiError} from '../api';
import {PageTitle,SectionCard,StatusPill,formatNumber} from '../components/ui';
import {isPrototype} from '../mode';
import {useApp} from '../store';
import {LogsPage} from './Operations';
import './operations.css';

type ObsTab='overview'|'builds'|'agent'|'chat'|'billing';

type TraceSummary={
 traceId:string;rootType:string;rootId:string;title:string;status:string;
 tokens:number|null;duration:number|null;time:string;createdAt?:string|null;
 attrs?:Record<string,unknown>;
};

type TraceDetail={
 trace:TraceSummary;
 steps:Array<{spanId:string;name:string;kind:string;status:string;duration:number|null;tokens:number|null;model?:string|null;error?:string|null;attrs?:Record<string,unknown>}>;
 buildStages:Array<{stage:string;status:string;duration:number|null;tokens:number|null;model?:string|null;error?:string|null;attrs?:Record<string,unknown>}>;
 input?:string|null;output?:string|null;error?:string|null;sources?:unknown[];
 toolCalls:unknown[];skillCalls:unknown[];harnessErrors:unknown[];gaps:string[];
};

type BillingRow={source:string;calls:number;tokensKnown:number;tokensUnknownCount:number};

const AGENT_FIELD_ROWS=[
 {field:'单次输入',path:'input.prompt / variables',note:'应用 run.input；脱敏策略后续'},
 {field:'单次输出',path:'output.text',note:'应用 run.output'},
 {field:'运行状态',path:'status',note:'running|success|failed|cancelled'},
 {field:'工具调用状态',path:'toolCalls[].status',note:'缺口 · API 返回空数组'},
 {field:'Skill 调用',path:'skillCalls[]',note:'缺口 · API 返回空数组'},
 {field:'单次 token',path:'tokens',note:'供应商返回为准；缺失为 null'},
 {field:'调用上下文',path:'applicationId,mode,revision,traceId',note:'与 application_run 互链'},
 {field:'Harness 异常',path:'harnessErrors[]',note:'缺口 · API 返回空数组'},
];

const ROOT_LABEL:Record<string,string>={chat:'对话',retrieval:'检索',import:'构建',application:'应用'};
const STAGE_LABEL:Record<string,string>={
 upload_received:'上传接收',parse:'解析',chunk:'切块',metadata_extract:'元数据',index:'索引',publish:'发布',
};

function statusPill(s:string){
 if(s==='success'||s==='succeeded')return 'success';
 if(s==='failed'||s==='error')return 'failed';
 if(s==='cancelled'||s==='canceled')return 'cancelled';
 if(s==='running'||s==='processing')return 'processing';
 if(s==='review'||s==='degraded'||s==='pending')return 'review';
 return 'processing';
}

function formatDuration(v:number|null|undefined){
 if(v===null||v===undefined)return '—';
 return `${Number(v).toFixed(2)}s`;
}

export default function ObservabilityPage(){
 const {logs,tasks,role,refresh}=useApp();
 const [tab,setTab]=useState<ObsTab>('chat');
 const [overview,setOverview]=useState<{requests:number;failed:number;tokensKnown:number;tokensUnknownCount:number;buildsRunning:number;byRootType:Record<string,number>;recent:TraceSummary[]} | null>(null);
 const [traces,setTraces]=useState<TraceSummary[]>([]);
 const [billing,setBilling]=useState<{items:BillingRow[];pricingConfigured:boolean;notice:string}|null>(null);
 const [traceQuery,setTraceQuery]=useState('');
 const [rootFilter,setRootFilter]=useState('all');
 const [loading,setLoading]=useState(false);
 const [error,setError]=useState('');
 const [selected,setSelected]=useState<TraceDetail|null>(null);
 const [toCaseBusy,setToCaseBusy]=useState<'good'|'bad'|''>('');
 const [detailLoading,setDetailLoading]=useState(false);

 const load=useCallback(async()=>{
  setLoading(true);setError('');
  try{
   const [ov,tr,bill]=await Promise.all([
    api<any>('/observability/overview'),
    api<any>('/observability/traces?limit=100'),
    api<any>('/observability/billing'),
   ]);
   setOverview(ov);setTraces(tr.items||[]);setBilling(bill);
  }catch(e){
   setError((e as ApiError).message||'观测接口不可用');
   // Fallback projection from workspace state when API missing (prototype/old backend)
   const projected:TraceSummary[]=logs.map(l=>({
    traceId:(l as any).traceId||l.id,rootType:l.source==='import'?'import':l.source,rootId:l.id,
    title:l.question,status:l.status,tokens:l.tokens,duration:l.duration,time:l.time,createdAt:undefined,
    attrs:{kbName:l.kbName,source:l.source},
   }));
   for(const t of tasks){
    if(!projected.some(p=>p.traceId===((t as any).traceId||t.id))){
     projected.push({
      traceId:(t as any).traceId||t.id,rootType:'import',rootId:t.id,title:`导入：${t.name}`,
      status:t.status,tokens:null,duration:null,time:t.time,attrs:{stage:t.stage,progress:t.progress},
     });
    }
   }
   setTraces(projected);
   setOverview({
    requests:projected.length,
    failed:projected.filter(p=>p.status==='failed').length,
    tokensKnown:projected.reduce((s,p)=>s+(p.tokens||0),0),
    tokensUnknownCount:projected.filter(p=>p.tokens===null).length,
    buildsRunning:tasks.filter(t=>t.status==='processing').length,
    byRootType:{},
    recent:projected.slice(0,20),
   });
   setBilling({
    items:Object.entries(logs.reduce((acc:Record<string,{source:string;calls:number;tokensKnown:number;tokensUnknownCount:number}>,l)=>{
     const s=l.source;const b=acc[s]||(acc[s]={source:s,calls:0,tokensKnown:0,tokensUnknownCount:0});
     b.calls++;if(typeof l.tokens==='number')b.tokensKnown+=l.tokens;else b.tokensUnknownCount++;return acc;
    },{})).map(([,v])=>v),
    pricingConfigured:false,
    notice:'观测 API 不可用时的本地 logs 投影；未配置单价。',
   });
  }finally{setLoading(false)}
 },[logs,tasks]);

 useEffect(()=>{load()},[load]);

 const openTrace=async(traceId:string)=>{
  setDetailLoading(true);
  try{
   const detail=await api<TraceDetail>(`/observability/traces/${encodeURIComponent(traceId)}`);
   setSelected(detail);
  }catch(e){
   // Minimal local fallback from logs
   const log=logs.find(l=>l.id===traceId||(l as any).traceId===traceId);
   const task=tasks.find(t=>t.id===traceId||(t as any).traceId===traceId);
   if(log||task){
    setSelected({
     trace:{
      traceId,rootType:log?(log.source==='import'?'import':log.source):'import',rootId:traceId,
      title:log?.question||`导入：${task?.name||''}`,status:log?.status||task?.status||'unknown',
      tokens:log?.tokens??null,duration:log?.duration??null,time:log?.time||task?.time||'',
     },
     steps:(log?.steps||[]).map((s,i)=>({spanId:`local:${i}`,name:s.name,kind:'internal',status:s.status,duration:s.duration,tokens:s.tokens,model:s.model})),
     buildStages:[],input:log?.question,output:log?.answer,error:task?.error,sources:[],
     toolCalls:[],skillCalls:[],harnessErrors:[],gaps:['详情来自本地投影，非 /observability/traces'],
    });
   }else{
    setError((e as ApiError).message||'无法打开追踪');
   }
  }finally{setDetailLoading(false)}
 };

 const filtered=useMemo(()=>{
  const needle=traceQuery.trim().toLowerCase();
  return traces.filter(t=>{
   if(rootFilter!=='all'&&t.rootType!==rootFilter)return false;
   if(!needle)return true;
   return t.traceId.toLowerCase().includes(needle)||(t.title||'').toLowerCase().includes(needle);
  });
 },[traces,traceQuery,rootFilter]);

 const builds=useMemo(()=>filtered.filter(t=>t.rootType==='import'),[filtered]);
 const agents=useMemo(()=>filtered.filter(t=>t.rootType==='application'),[filtered]);

 const ov=overview||{requests:0,failed:0,tokensKnown:0,tokensUnknownCount:0,buildsRunning:0,byRootType:{},recent:[]};

 const toCase=async(label:'good'|'bad')=>{
  if(!selected||toCaseBusy)return;
  setToCaseBusy(label);
  try{
   const res=await api<{ok:boolean;error?:string|null;case?:{id:string;label:string;query:string}|null}>(`/observability/traces/${encodeURIComponent(selected.trace.traceId)}/to-case`,json('POST',{label,query:selected.input||undefined,answer:selected.output||undefined}));
   if(res.ok&&res.case)message.success(`已生成 ${label==='good'?'Good':'Bad'} Case：${res.case.id.slice(0,12)}…`);
   else message.warning(res.error||'未能生成 Case（未阻断主流程）');
  }catch(e){
   message.warning((e as Error).message||'生成 Case 失败（未阻断主流程）');
  }finally{setToCaseBusy('');}
 };

 return <div className="ops-page page-content obs-page">
  <PageTitle
   eyebrow="OBSERVABILITY CENTER"
   title="观测中心"
   description="用真实 traceId 串联知识库构建、对话检索与应用运行。缺域返回空数组，不伪造 token。"
   actions={<Tag bordered={false} color={error?'orange':'green'}>{error?'本地投影 / 降级':'真实 traceId'}</Tag>}
  />
  {error&&<Alert type="warning" showIcon style={{marginBottom:18}} message={error} description="已尽量用现有 logs/tasks 投影；修复后端后点刷新。"/>}
  {!error&&isPrototype&&<Alert type="info" showIcon style={{marginBottom:18}} message="原型模式走本地 stub" description="prototype/api 已提供 /observability/* 投影。"/>}

  <div style={{display:'flex',gap:12,marginBottom:12,flexWrap:'wrap',alignItems:'center'}}>
   <Input
    style={{maxWidth:320}}
    allowClear
    prefix={<Search size={15}/>}
    placeholder="按 traceId / 标题搜索"
    value={traceQuery}
    onChange={e=>setTraceQuery(e.target.value)}
    onPressEnter={()=>{const id=traceQuery.trim();if(id)openTrace(id)}}
   />
   <Select
    style={{width:140}}
    value={rootFilter}
    onChange={setRootFilter}
    options={[
     {value:'all',label:'全部类型'},
     {value:'import',label:'知识构建'},
     {value:'application',label:'应用运行'},
     {value:'chat',label:'对话'},
     {value:'retrieval',label:'检索'},
    ]}
   />
   <Button onClick={()=>{refresh();load()}} loading={loading}>刷新</Button>
   <Button type="primary" disabled={!traceQuery.trim()} onClick={()=>openTrace(traceQuery.trim())}>打开 trace</Button>
  </div>

  <Tabs
   activeKey={tab}
   onChange={k=>setTab(k as ObsTab)}
   items={[
    {key:'overview',label:<span><Radar size={14}/> 总览</span>},
    {key:'builds',label:<span><Database size={14}/> 知识库构建</span>},
    {key:'agent',label:<span><Bot size={14}/> Agent 调用</span>},
    {key:'chat',label:<span><MessageSquare size={14}/> 对话日志</span>},
    {key:'billing',label:<span><Coins size={14}/> 计费消耗</span>},
   ]}
  />

  {tab==='overview'&&<>
   <div className="ops-stats">
    <div className="ops-metric"><div>追踪条数<i><Activity size={15}/></i></div><b>{formatNumber(ov.requests)}<small>条</small></b><p>log / task / application_run 投影</p></div>
    <div className="ops-metric"><div>失败<i><Workflow size={15}/></i></div><b>{formatNumber(ov.failed)}<small>条</small></b><p>status=failed</p></div>
    <div className="ops-metric"><div>已知 Tokens<i><Coins size={15}/></i></div><b>{formatNumber(ov.tokensKnown)}</b><p>未知 {formatNumber(ov.tokensUnknownCount)} 条</p></div>
    <div className="ops-metric"><div>构建中任务<i><Database size={15}/></i></div><b>{formatNumber(ov.buildsRunning)}<small>个</small></b><p>task.status=processing</p></div>
   </div>
   <SectionCard title="最近追踪" subtitle="点击 traceId 打开详情抽屉">
    <Table
     rowKey="traceId"
     size="middle"
     loading={loading}
     pagination={{pageSize:8,showSizeChanger:false}}
     dataSource={filtered.slice(0,50)}
     locale={{emptyText:<Empty description="暂无追踪数据"/>}}
     columns={[
      {title:'traceId',dataIndex:'traceId',width:180,render:v=><button className="ops-log-question" onClick={()=>openTrace(v)}><b className="mono">{v}</b></button>},
      {title:'类型',dataIndex:'rootType',width:90,render:v=><Tag>{ROOT_LABEL[v]||v}</Tag>},
      {title:'摘要',dataIndex:'title',ellipsis:true},
      {title:'状态',dataIndex:'status',width:100,render:s=><StatusPill status={statusPill(s)}/>},
      {title:'Tokens',width:90,render:(_,r)=><span className="mono">{r.tokens===null?'未知':formatNumber(r.tokens)}</span>},
      {title:'耗时',width:90,render:(_,r)=><span className="mono">{formatDuration(r.duration)}</span>},
      {title:'时间',dataIndex:'time',width:120},
      {title:'',width:48,render:(_,r)=><Button type="text" icon={<ChevronRight size={16}/>} onClick={()=>openTrace(r.traceId)}/>},
     ]}
    />
   </SectionCard>
  </>}

  {tab==='builds'&&<>
   <SectionCard title="构建任务流水线" subtitle="traceId = task.id；阶段来自 import log steps / task.stage，缺耗时标 —">
    <Table
     rowKey="traceId"
     size="middle"
     loading={loading}
     pagination={{pageSize:8,showSizeChanger:false}}
     dataSource={builds}
     locale={{emptyText:<Empty description="暂无构建追踪。上传文档后会出现。"/>}}
     scroll={{x:960}}
     columns={[
      {title:'traceId',dataIndex:'traceId',width:180,render:v=><button className="ops-log-question" onClick={()=>openTrace(v)}><code className="mono">{v}</code></button>},
      {title:'文档',dataIndex:'title',ellipsis:true},
      {title:'知识库',width:140,render:(_,r)=>String(r.attrs?.kbName||r.attrs?.kbId||'—')},
      {title:'阶段',width:140,render:(_,r)=>String(r.attrs?.stage||'—')},
      {title:'状态',dataIndex:'status',width:100,render:s=><StatusPill status={statusPill(s)}/>},
      {title:'Tokens',width:90,render:(_,r)=><span className="mono">{r.tokens===null?'未知':formatNumber(r.tokens)}</span>},
      {title:'耗时',width:90,render:(_,r)=><span className="mono">{formatDuration(r.duration)}</span>},
      {title:'时间',dataIndex:'time',width:120},
     ]}
    />
    <p className="ops-data-caption">标准阶段：upload_received → parse → chunk → metadata_extract → index → publish。无独立计时的阶段 duration 为 null（界面显示 —）。</p>
   </SectionCard>
  </>}

  {tab==='agent'&&<>
   <SectionCard title="Agent / 应用字段对照" subtitle="以 application_run 为主；工具 / Skill / Harness 标缺口">
    <Table rowKey="field" size="small" pagination={false} dataSource={AGENT_FIELD_ROWS}
     columns={[{title:'需求字段',dataIndex:'field',width:140},{title:'设计落点',dataIndex:'path'},{title:'说明 / 现状',dataIndex:'note'}]}/>
   </SectionCard>
   <SectionCard title="应用运行列表" subtitle="rootType=application · traceId = runId">
    <Table
     rowKey="traceId"
     size="middle"
     loading={loading}
     pagination={{pageSize:8,showSizeChanger:false}}
     dataSource={agents}
     locale={{emptyText:<Empty description="暂无应用运行。在应用页执行一次 run 后出现。"/>}}
     scroll={{x:1000}}
     columns={[
      {title:'traceId',dataIndex:'traceId',width:180,render:v=><button className="ops-log-question" onClick={()=>openTrace(v)}><b className="mono">{v}</b></button>},
      {title:'应用',dataIndex:'title',width:160},
      {title:'状态',dataIndex:'status',width:100,render:s=><StatusPill status={statusPill(s)}/>},
      {title:'模式',width:100,render:(_,r)=>String(r.attrs?.mode||'—')},
      {title:'Tokens',width:90,render:(_,r)=><span className="mono">{r.tokens===null?'未知':formatNumber(r.tokens)}</span>},
      {title:'工具/Skill',width:120,render:()=><Tag>缺口</Tag>},
      {title:'Harness',width:100,render:()=><Tag>缺口</Tag>},
      {title:'时间',dataIndex:'time',width:140},
      {title:'',width:48,render:(_,r)=><Button type="text" icon={<ChevronRight size={16}/>} onClick={()=>openTrace(r.traceId)}/>},
     ]}
    />
   </SectionCard>
  </>}

  {tab==='chat'&&<>
   <LogsPage embedded/>
   <p className="ops-data-caption">对话 / 检索 log.id 即 traceId（req-…）。可用上方搜索框打开同一条链路。</p>
  </>}

  {tab==='billing'&&<>
   <div className="ops-stats">
    <div className="ops-metric"><div>已知 Tokens<i><Coins size={15}/></i></div><b>{formatNumber(ov.tokensKnown)}</b><p>logs + application_run 聚合</p></div>
    <div className="ops-metric"><div>预估费用<i><Activity size={15}/></i></div><b>—</b><p>{billing?.pricingConfigured?'已配置单价':'未配置单价，不估算金额'}</p></div>
   </div>
   <SectionCard title="按场景汇总" subtitle={billing?.notice||'仅已知 token'}>
    <Table
     rowKey="source"
     loading={loading}
     pagination={false}
     dataSource={billing?.items||[]}
     locale={{emptyText:<Empty description="暂无用量数据"/>}}
     columns={[
      {title:'场景',dataIndex:'source',render:s=>ROOT_LABEL[s]||s},
      {title:'调用次数',dataIndex:'calls',width:100},
      {title:'已知 Tokens',dataIndex:'tokensKnown',width:120,render:n=><span className="mono">{formatNumber(n)}</span>},
      {title:'未知条数',dataIndex:'tokensUnknownCount',width:100},
      {title:'预估金额',width:120,render:()=>'—'},
     ]}
    />
   </SectionCard>
  </>}

  <Drawer
   title={selected?`追踪详情 · ${selected.trace.traceId}`:'追踪详情'}
   open={!!selected}
   onClose={()=>setSelected(null)}
   width={520}
  >
   {detailLoading&&<p>加载中…</p>}
   {selected&&!detailLoading&&<div className="ops-log-detail">
    <div className="ops-detail-id"><code>{selected.trace.traceId}</code><StatusPill status={statusPill(selected.trace.status)}/><Tag>{ROOT_LABEL[selected.trace.rootType]||selected.trace.rootType}</Tag></div>
    {!isPrototype&&<div style={{margin:'12px 0'}}><Space><Button size="small" icon={<ThumbsUp size={14}/>} loading={toCaseBusy==='good'} disabled={!!toCaseBusy} onClick={()=>void toCase('good')}>标为 Good Case</Button><Button size="small" icon={<ThumbsDown size={14}/>} loading={toCaseBusy==='bad'} disabled={!!toCaseBusy} onClick={()=>void toCase('bad')}>标为 Bad Case</Button></Space><p className="ops-data-caption">写入 eval-case，可供评测集导入；失败只提示不阻断。</p></div>}
    <p className="ops-data-caption">rootId={selected.trace.rootId} · tokens={selected.trace.tokens===null?'未知':formatNumber(selected.trace.tokens)} · 耗时 {formatDuration(selected.trace.duration)}</p>
    {selected.input!=null&&<><h4>输入</h4><div className="ops-content-box">{selected.input||'（空）'}</div></>}
    {selected.output!=null&&<><h4>输出</h4><div className="ops-content-box">{selected.output||'（空）'}</div></>}
    {selected.error&&<><h4>错误</h4><div className="ops-content-box">{selected.error}</div></>}
    {selected.buildStages.length>0&&<>
     <h4>构建流水线</h4>
     {selected.buildStages.map((s,i)=>(
      <div className="ops-step" key={s.stage}>
       <span className="ops-step-number">{i+1}</span>
       <div>
        <b>{STAGE_LABEL[s.stage]||s.stage} · {s.status}</b>
        <small className="mono">耗时 {formatDuration(s.duration)} · tokens {s.tokens===null||s.tokens===undefined?'—':formatNumber(s.tokens)}{s.model?` · ${s.model}`:''}</small>
        {s.error&&<small style={{color:'#b42318'}}>{s.error}</small>}
       </div>
      </div>
     ))}
    </>}
    {selected.steps.length>0&&<>
     <h4>步骤 / Spans</h4>
     {selected.steps.map((s,i)=>(
      <div className="ops-step" key={s.spanId||i}>
       <span className="ops-step-number">{i+1}</span>
       <div>
        <b>{s.name} · {s.status}</b>
        <small className="mono">{s.kind} · {formatDuration(s.duration)} · tokens {s.tokens===null?'未知':formatNumber(s.tokens??0)}</small>
        {s.error&&<small style={{color:'#b42318'}}>{s.error}</small>}
       </div>
      </div>
     ))}
    </>}
    {selected.steps.length===0&&selected.buildStages.length===0&&<Empty description="无步骤数据"/>}
    <h4>工具 / Skill / Harness</h4>
    <div className="ops-content-box">
     toolCalls: {selected.toolCalls.length} · skillCalls: {selected.skillCalls.length} · harnessErrors: {selected.harnessErrors.length}
     {selected.gaps.length>0&&<div style={{marginTop:8}}>{selected.gaps.map(g=><div key={g}>· {g}</div>)}</div>}
    </div>
    <p className="ops-data-caption">角色 {role} · 详见 docs/observability-traceid.md</p>
   </div>}
  </Drawer>
 </div>;
}
