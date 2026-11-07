import {useRef,useState} from 'react';
import type {KnowledgeDocument} from './model';

type Props = {
  query: string;
  hits: KnowledgeDocument[];
  temporaryCount: number;
  importing: boolean;
  importError: string;
  importMessage: string;
  onImport: (file: File) => Promise<void>;
  onRemove: (id?: string) => void;
  onQuery: (value: string) => void;
  onSearch: (value: string) => void;
  onDownload: (doc: KnowledgeDocument) => void;
  onOpenApplications: () => void;
};

function KnowledgeCard({doc,busy,onDownload,onRemove}: {doc:KnowledgeDocument;busy:boolean;onDownload:Props['onDownload'];onRemove:Props['onRemove']}) {
  const [expanded,setExpanded]=useState(false);
  const temporary=doc.kind==='temporary';
  return <article>
    <div className="knowledge-doc-heading"><span className="knowledge-doc-icon" aria-hidden="true">文</span><span>{doc.source}</span></div>
    <h3>{doc.title}</h3>
    <p>{doc.text.slice(0,320)}{doc.text.length>320?'…':''}</p>
    {temporary&&<div className="temporary-doc-actions">
      <button className="text-button" aria-expanded={expanded} onClick={()=>setExpanded(value=>!value)}>{expanded?'收起原文':'展开原文'}</button>
      <button className="text-button" disabled={busy} aria-label={'移除临时资料：'+doc.title} onClick={()=>onRemove(doc.id)}>移除</button>
    </div>}
    {expanded&&<div className="temporary-original"><pre>{doc.text.slice(0,10000)}</pre>{doc.text.length>10000&&<small>预览前 10000 个字符，完整内容可下载原文件查看。</small>}</div>}
    <div className="knowledge-doc-footer"><small>{temporary?'仅当前页面 · 未上传后台':'原文可追溯 · 合成示例'}</small><button className="secondary"
      onClick={()=>onDownload(doc)}>{temporary?'下载原文件':'下载合成原文'}</button></div>
  </article>;
}

export default function KnowledgeExplorer({query, hits, temporaryCount, importing, importError, importMessage, onImport, onRemove, onQuery, onSearch, onDownload, onOpenApplications}: Props) {
  const fileInput=useRef<HTMLInputElement>(null);
  return <>
    <section className="knowledge-intro">
      <span className="demo-caption">EXPLORE KNOWLEDGE</span>
      <h1>探索知识</h1>
      <p>先问业务问题，查找相关原文，再进入对应业务。</p>
      <div className="knowledge-import">
        <div><strong>用自己的资料试一试</strong><p>TXT / MD / CSV · 单份最多 1 MB<br/>仅在本页读取，刷新或重置后清空。请用合成或脱敏文件体验。</p></div>
        <button className="primary" disabled={importing} onClick={()=>fileInput.current?.click()}>{importing?'正在解析…':'临时导入资料'}</button>
        <input id="temporary-knowledge-file" ref={fileInput} type="file" accept=".txt,.md,.csv" hidden aria-label="选择临时知识文件" disabled={importing} onChange={event=>{
          const file=event.currentTarget.files?.[0];event.currentTarget.value='';if(file)void onImport(file);
        }}/>
      </div>
      {importError&&<p className="demo-error temporary-import-message" role="alert">{importError}</p>}
      {importMessage&&<p className="demo-notice temporary-import-message" role="status">{importMessage}</p>}
      {temporaryCount>0&&<div className="temporary-import-summary"><span>已临时导入 {temporaryCount} / 10 份 · 合计最多 5 MB</span><button className="text-button" disabled={importing} onClick={()=>onRemove()}>清空临时资料</button></div>}
      <form className="knowledge-search" role="search" onSubmit={event => {
        event.preventDefault();
        onSearch(query);
      }}>
        <label htmlFor="knowledge-query">知识问答 / 搜索原文</label>
        <div className="knowledge-search-box">
          <span aria-hidden="true">⌕</span>
          <input id="knowledge-query" type="search" value={query} maxLength={200}
            onChange={event => onQuery(event.target.value)} placeholder="例如：设计出方案后，采购清单由谁填写？"/>
          <button className="primary" type="submit">查找依据</button>
        </div>
      </form>
      <div className="knowledge-topics" aria-label="推荐搜索">
        <span>试试搜索</span>
        {['采购', '到货', '变更'].map(topic => <button key={topic} type="button"
          onClick={() => onSearch(topic)}>{topic}<span aria-hidden="true"> ↗</span></button>)}
      </div>
      <p className="knowledge-scope">搜索内置合成资料与本页临时导入的原文。不调用 AI，不上传后台。</p>
    </section>

    <section className="knowledge-library" aria-labelledby="knowledge-library-title">
      <div className="demo-section-heading">
        <div><span className="demo-caption">PROJECT LIBRARY</span><h2 id="knowledge-library-title">知识资料</h2></div>
        <span className="demo-pill">合成示例 + 本页临时资料</span>
      </div>
      <p className="knowledge-result-count" role="status">找到 {hits.length} 份资料</p>
      <div className="demo-docs">
        {hits.map(doc => <KnowledgeCard key={doc.id} doc={doc} busy={importing} onDownload={onDownload} onRemove={onRemove}/>)}
      </div>
      {hits.length === 0 && <div className="knowledge-empty">
        <h3>暂未找到相关资料</h3><p>试试“到货”或“变更”，也可以查看全部资料。</p>
        <button className="secondary" onClick={() => onSearch('')}>查看全部资料</button>
      </div>}
    </section>

    <section className="knowledge-next">
      <div><span className="demo-caption">FROM KNOWLEDGE TO ACTION</span><h2>让知识成为下一步行动</h2><p>在应用生成中，将处理建议编排为可试运行的规则流程。</p></div>
      <button className="secondary" onClick={onOpenApplications}>进入应用生成 →</button>
    </section>
  </>;
}
