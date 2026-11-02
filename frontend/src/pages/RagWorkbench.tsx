import {useEffect, useState} from 'react';
import {Alert, Button, Card, Empty, Input, InputNumber, Select, Space, Switch, Table, Tabs, Tag, Typography} from 'antd';
import {api, json} from '../api';
import {useApp} from '../store';
import {isPrototype} from '../mode';
import {PageTitle} from '../components/ui';

type Source = {name:string; url:string; revision:string; installedPath:string; integration:string};
type Report = {options:{topK:number}; id:string; createdAt:string; status:string; total:number; completed:number; corpusStable:boolean; summary:Record<string,number|null>; judge:string; metricScope:string; rows:any[]};

export default function RagWorkbench(){
  const {kbs,docs}=useApp();
  const [kb,setKb]=useState('');
  const selected=kb||kbs[0]?.id||'';
  const [sources,setSources]=useState<Source[]>([]);
  const [engine,setEngine]=useState<any>(null);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [busy,setBusy]=useState(false);
  const [audit,setAudit]=useState<any>(null);
  const [query,setQuery]=useState('');
  const [includeDrafts,setIncludeDrafts]=useState(false);
  const [hits,setHits]=useState<any[]|null>(null);
  const [cases,setCases]=useState('');
  const [topK,setTopK]=useState(5);
  const [mode,setMode]=useState('keyword');
  const [evalEngine,setEvalEngine]=useState('platform');
  const [rerank,setRerank]=useState(false);
  const [report,setReport]=useState<Report|null>(null);
  const [history,setHistory]=useState<Report[]>([]);
  useEffect(()=>{
    if(isPrototype)return;
    const controller=new AbortController();
    api('/rag-workbench/capabilities',{signal:controller.signal}).then(data=>{setSources(data.sources);setEngine(data.engine)}).catch(e=>{if(!controller.signal.aborted)setError(e.message)});
    return()=>controller.abort();
  },[]);
  useEffect(()=>{
    setAudit(null);setHits(null);setReport(null);setHistory([]);setNotice('');
    if(!selected||isPrototype)return;
    const controller=new AbortController();
    api<Report[]>(`/rag-workbench/knowledge-bases/${encodeURIComponent(selected)}/evaluations`,{signal:controller.signal}).then(setHistory).catch(e=>{if(!controller.signal.aborted)setError(e.message)});
    return()=>controller.abort();
  },[selected]);
  async function run(fn:()=>Promise<void>){setBusy(true);setError('');setNotice('');try{await fn()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  const publishedCount=docs.filter(d=>d.kbId===selected&&d.status==='ready').length;
  const path=`/rag-workbench/knowledge-bases/${encodeURIComponent(selected)}`;
  if(isPrototype)return <div className="page-content"><Alert type="info" showIcon message="RAG 能力工作台需要真实后端" description="请打开 http://127.0.0.1:8000/#/rag-workbench；原型模式不会执行入库、评测或模型调用。"/></div>;
  const evaluate=()=>run(async()=>{
    let parsed:unknown;try{parsed=JSON.parse(cases)}catch{throw new Error('测试集必须是有效的 JSON 数组')}
    if(!Array.isArray(parsed)||!parsed.length)throw new Error('请填写至少一条测试用例');
    const result=await api<Report>(`${path}/evaluations`,json('POST',{cases:parsed,topK,mode,rerank,engine:evalEngine,includeDrafts:evalEngine==='local'&&includeDrafts}));
    setReport(result);setHistory(old=>[result,...old]);
  });
  const reportView=report&&<Space direction="vertical" style={{width:'100%'}}>
    <Alert type={report.status==='success'?'success':'warning'} showIcon message={`${report.status==='success'?'执行完成':'结果不完整'}：${report.completed}/${report.total} 条；语料${report.corpusStable?'保持一致':'发生变化'}`} description={report.judge}/>
    <Space wrap>{Object.entries(report.summary).map(([metric,value])=><Card key={metric} size="small"><strong>{({hit:'命中率',recall:'Recall',mrr:'MRR',ndcg:'nDCG'} as Record<string,string>)[metric]}@{report.options.topK}</strong><div style={{fontSize:26}}>{value===null?'未计算':value.toFixed(3)}</div></Card>)}</Space>
    <Typography.Text type="secondary">{report.metricScope}</Typography.Text>
    <Table rowKey={(_,i)=>String(i)} dataSource={report.rows} pagination={{pageSize:10}} scroll={{x:650}} columns={[{title:'问题',dataIndex:'query'},{title:'状态',dataIndex:'status',render:(s:string)=><Tag color={s==='success'?'green':'red'}>{s==='success'?'完成':'失败'}</Tag>},{title:'MRR',dataIndex:'mrr',render:(v:number)=>v?.toFixed(3)??'—'},{title:'召回',dataIndex:'recall',render:(v:number)=>v?.toFixed(3)??'—'},{title:'问题详情',render:(_,r)=>r.error||(r.degraded?'重排降级':'')}]} />
    <Space><Button onClick={()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=report.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}}>下载评测报告</Button><Button href={`/api${path}/evaluations/${encodeURIComponent(report.id)}/nvidia.zip`} target="_blank">导出 NVIDIA 评测包</Button></Space>
  </Space>;
  return <div className="page-content"><PageTitle eyebrow="RAG WORKBENCH" title="RAG 能力工作台" description="把资料入库、检索质量和本地引擎放在同一条可验证的工作流中。"/>
    <Space direction="vertical" size="large" style={{width:'100%'}}>
      {error&&<Alert type="error" showIcon closable onClose={()=>setError('')} message={error}/>}{notice&&<Alert type="success" showIcon message={notice}/>}
      <Space wrap><label htmlFor="rag-kb">知识库</label><Select id="rag-kb" aria-label="选择工作台知识库" value={selected||undefined} disabled={busy} onChange={setKb} style={{minWidth:260}} options={kbs.map(k=>({value:k.id,label:k.name}))}/><Tag color={engine?.status==='ok'?'green':'orange'}>{engine?.status==='ok'?'本地引擎在线':'本地引擎未连接'}</Tag><Typography.Text type="secondary">本地中文模型 · 512 维 · 独立索引</Typography.Text></Space>
      {!publishedCount&&<Alert type="warning" showIcon message="当前知识库尚无已发布资料" description="资料库导出与生产检索评测需要先检查并发布文档；若先验证本地引擎，可在“本地检索引擎”中打开“包含待检查资料”，仅用于管理端测试。"/>}
      <Tabs items={[
        {key:'quality',label:'入库与资料库',children:<Space direction="vertical" style={{width:'100%'}}>
          <Alert type="info" showIcon message="从已发布内容生成 Markdown 资料库" description="每份资料包含标题、版本、原件链接和来源位置；导出使用当前解析结果，不重新调用 OCR 或云模型。"/>
          <Space wrap><Button disabled={!selected||busy} loading={busy} onClick={()=>void run(async()=>setAudit(await api(`${path}/audit`)))}>检查入库质量</Button><Button disabled={!selected||busy} href={`/api${path}/vault.zip`} target="_blank">下载 Markdown Vault</Button></Space>
          {audit&&<><Space wrap><Tag>{audit.documentCount} 份文档</Tag><Tag>{audit.publishedCount} 份已发布</Tag><Tag>{audit.chunkCount} 个片段</Tag></Space><Table rowKey={(_,i)=>String(i)} size="small" dataSource={audit.issues} locale={{emptyText:'检查项未发现问题；内容正确性仍需核对原件'}} columns={[{title:'文档',dataIndex:'name'},{title:'检查发现',dataIndex:'problem'}]}/></>}
        </Space>},
        {key:'evaluate',label:'批量检索评测',children:<Space direction="vertical" style={{width:'100%'}}>
          <Alert type="info" showIcon message="用预先标注的参考文档评估检索" description="关键词模式无需模型调用；混合 / 语义检索和重排会调用已配置的服务并产生实际用量。NVIDIA 包导出还需为每条用例填写参考答案 answer。"/>
          <details><summary>查看当前评测范围文档 ID 与测试集格式</summary><ul>{docs.filter(d=>d.kbId===selected&&(d.status==='ready'||evalEngine==='local'&&includeDrafts&&d.status==='review')).map(d=><li key={d.id}>{d.name}：<code>{d.id}</code></li>)}</ul><pre>{'[\n  {"query": "你的问题", "expectedDocIds": ["已发布文档ID"], "answer": "人工核实的参考答案（可选）"}\n]'}</pre></details>
          <label htmlFor="rag-cases">测试集 JSON（最多 100 条）</label><Input.TextArea id="rag-cases" rows={7} value={cases} disabled={busy} onChange={e=>setCases(e.target.value)} placeholder="粘贴问题和预先标注的参考文档 ID，不从当前搜索结果生成答案标签"/>
          <Space wrap><label htmlFor="rag-eval-engine">评测引擎</label><Select id="rag-eval-engine" value={evalEngine} disabled={busy} onChange={setEvalEngine} style={{width:180}} options={[{value:"platform",label:"中台现有检索"},{value:"local",label:"knowledge-rag 本地"}]}/>{evalEngine==='local'&&<><Switch checked={includeDrafts} disabled={busy} onChange={setIncludeDrafts}/><span>包含待检查资料</span></>}<label htmlFor="rag-mode">检索模式</label><Select id="rag-mode" value={mode} disabled={busy||evalEngine==='local'} onChange={setMode} style={{width:140}} options={[{value:'keyword',label:'关键词（本地）'},{value:'hybrid',label:'混合检索'},{value:'semantic',label:'语义检索'}]}/><label htmlFor="rag-topk">Top K</label><InputNumber id="rag-topk" value={topK} min={1} max={20} disabled={busy} onChange={n=>setTopK(n||5)}/><Switch checked={rerank} disabled={busy||evalEngine==='local'} onChange={setRerank} checkedChildren="重排开" unCheckedChildren="重排关"/><Button type="primary" loading={busy} disabled={!selected||!cases.trim()} onClick={()=>void evaluate()}>运行评测</Button></Space>
          {reportView}
          {history.length>0&&<><Typography.Title level={5}>最近评测</Typography.Title><Select aria-label="查看历史评测" style={{width:'100%'}} value={report?.id} onChange={id=>setReport(history.find(r=>r.id===id)||null)} options={history.map(r=>({value:r.id,label:`${r.createdAt} · ${r.completed}/${r.total} · ${r.status}`}))}/></>}
        </Space>},
        {key:'engine',label:'本地检索引擎',children:<Space direction="vertical" style={{width:'100%'}}>
          <Alert type="info" showIcon message="lyonzin/knowledge-rag · 本地 Embedding + ChromaDB + 混合检索" description="将当前知识库已发布的文字快照复制到独立索引；首次同步下载约 90MB 中文模型。包含待检查资料时仅用于管理端检索测试，不会发布到在线对话；更新、停用或删除文档后需重新同步。此页保留独立快照用于对比；要用于正式问答，请在“模型与服务”启用本地中文向量，在知识库设置绑定后发布文档。"/>
          <Space><Switch aria-label="包含待检查资料" checked={includeDrafts} disabled={busy} onChange={value=>{setIncludeDrafts(value);setHits(null)}}/><span>包含待检查资料（仅管理端测试）</span></Space>
          <Button disabled={!selected||busy||engine?.status!=='ok'} loading={busy} onClick={()=>void run(async()=>{const r=await api(`${path}/local-index?include_drafts=${includeDrafts}`,json('POST',{}));setNotice(`已同步 ${r.indexedDocuments} 份文档到本地引擎`)})}>同步所选范围到本地索引</Button>
          <label htmlFor="rag-query">检索问题</label><Input id="rag-query" disabled={busy} value={query} onChange={e=>setQuery(e.target.value)} placeholder="输入需要查找的问题"/><Button type="primary" disabled={!selected||!query.trim()||busy} loading={busy} onClick={()=>void run(async()=>setHits((await api(`${path}/local-search`,json('POST',{query,topK,includeDrafts}))).results))}>本地检索</Button>
          {hits!==null&&(hits.length?hits.map((hit,i)=><Card size="small" key={i} title={hit.name} extra={<a href={hit.originalUrl} target="_blank" rel="noreferrer">核对原件</a>}><Tag>{hit.draft?'待检查资料':`v${hit.version}`}</Tag><Typography.Paragraph style={{whiteSpace:'pre-wrap'}}>{hit.content}</Typography.Paragraph></Card>):<Empty description="当前快照未命中相关资料"/>)}
        </Space>},
        {key:'sources',label:'已安装技能',children:<Space direction="vertical" style={{width:'100%'}}><Alert type="info" showIcon message="技能文件与运行能力分别记录" description="这些技能在本项目后续对话中可用；NVIDIA rag-eval 的完整 RAGAS 评测依赖 NVIDIA Blueprint、评审模型和凭证，本页不会把检索指标当作 RAGAS 分数。"/>{sources.map(source=><Card key={source.name} size="small" title={source.name} extra={<a href={source.url} target="_blank" rel="noreferrer">GitHub 来源</a>}><p>{source.integration}</p><Typography.Text type="secondary">版本 {source.revision.slice(0,12)} · {source.installedPath}</Typography.Text></Card>)}</Space>},
      ]}/>
    </Space>
  </div>;
}
