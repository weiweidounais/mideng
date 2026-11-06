import {demoDocs} from './model';

type Props = {
  query: string;
  hits: typeof demoDocs;
  onQuery: (value: string) => void;
  onSearch: (value: string) => void;
  onDownload: (doc: (typeof demoDocs)[number]) => void;
  onOpenApplications: () => void;
};

export default function KnowledgeExplorer({query, hits, onQuery, onSearch, onDownload, onOpenApplications}: Props) {
  return <>
    <section className="knowledge-intro">
      <span className="demo-caption">EXPLORE KNOWLEDGE</span>
      <h1>探索知识</h1>
      <p>找到需要的资料，让下一步有据可循。</p>
      <form className="knowledge-search" role="search" onSubmit={event => {
        event.preventDefault();
        onSearch(query);
      }}>
        <label htmlFor="knowledge-query">搜索知识原文</label>
        <div className="knowledge-search-box">
          <span aria-hidden="true">⌕</span>
          <input id="knowledge-query" type="search" value={query} maxLength={200}
            onChange={event => onQuery(event.target.value)} placeholder="搜索采购、到货验收、变更等资料"/>
          <button className="primary" type="submit">搜索知识</button>
        </div>
      </form>
      <div className="knowledge-topics" aria-label="推荐搜索">
        <span>试试搜索</span>
        {['采购', '到货', '变更'].map(topic => <button key={topic} type="button"
          onClick={() => onSearch(topic)}>{topic}<span aria-hidden="true"> ↗</span></button>)}
      </div>
      <p className="knowledge-scope">当前仅搜索两份合成示例原文，不调用 AI，也不连接企业资料。</p>
    </section>

    <section className="knowledge-library" aria-labelledby="knowledge-library-title">
      <div className="demo-section-heading">
        <div><span className="demo-caption">PROJECT LIBRARY</span><h2 id="knowledge-library-title">知识资料</h2></div>
        <span className="demo-pill">公开合成知识空间</span>
      </div>
      <p className="knowledge-result-count" role="status">找到 {hits.length} 份合成资料</p>
      <div className="demo-docs">
        {hits.map(doc => <article key={doc.id}>
          <div className="knowledge-doc-heading"><span className="knowledge-doc-icon" aria-hidden="true">文</span><span>{doc.source}</span></div>
          <h3>{doc.title}</h3>
          <p>{doc.text}</p>
          <div className="knowledge-doc-footer"><small>原文可追溯 · 合成示例</small><button className="secondary"
            onClick={() => onDownload(doc)}>下载合成原文</button></div>
        </article>)}
      </div>
      {hits.length === 0 && <div className="knowledge-empty">
        <h3>暂未找到相关资料</h3><p>试试“到货”或“变更”，也可以查看全部合成资料。</p>
        <button className="secondary" onClick={() => onSearch('')}>查看全部资料</button>
      </div>}
    </section>

    <section className="knowledge-next">
      <div><span className="demo-caption">FROM KNOWLEDGE TO ACTION</span><h2>让知识成为下一步行动</h2><p>在应用生成中，将处理建议编排为可试运行的规则流程。</p></div>
      <button className="secondary" onClick={onOpenApplications}>进入应用生成 →</button>
    </section>
  </>;
}
