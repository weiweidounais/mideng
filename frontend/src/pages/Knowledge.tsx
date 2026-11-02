import {isPrototype} from '../mode';
import { useMemo, useRef, useState, useEffect, type DragEvent } from 'react';
import { Alert, Button, Checkbox, Drawer, Dropdown, Form, Input, InputNumber, Modal, Popconfirm, Progress, Select, Slider, Space, Steps, Switch, Table, Tabs, Tag, Tooltip } from 'antd';
import { ArrowDownToLine, ArrowLeft, ArrowRight, BookOpen, Check, ChevronRight, Clock3, CloudUpload, Database, Ellipsis, FileSearch, Files, Filter, FolderOpen, Image, Layers3, ListFilter, LoaderCircle, Pencil, Plus, RefreshCw, Search, Settings2, ShieldCheck, Sparkles, Trash2, X } from 'lucide-react';
import { useApp } from '../store';
import type { Chunk, DocMetadata, KnowledgeBase, KnowledgeDoc } from '../types';
import { api, json } from '../api';
import { EmptyState, FileIcon, PageTitle, SectionCard, StatusPill, downloadText, formatNumber, nowLabel } from '../components/ui';
import './knowledge.css';

const categories = ['行政制度', '产品知识', '技术研发', '人力资源', '客户服务', '市场运营'];
const allowedKinds = ['doc', 'docx', 'pdf', 'md', 'png', 'jpg', 'jpeg', 'xlsx', 'xls', 'csv', ...(!isPrototype?['txt','json','html','htm','pptx','ipynb','py','js','ts','sql','yaml','yml']:[])];
type PendingFile = { name: string; kind: string; size: string; file:File; duplicate?: boolean; replacementFor?:string };
type Match = { doc: KnowledgeDoc; chunk: Chunk; score: number };

function LibraryMark({ color, small = false }: { color: string; small?: boolean }) {
  return <div className={`library-mark library-${color} ${small ? 'small' : ''}`}><BookOpen size={small ? 21 : 27} strokeWidth={1.8} /><span /></div>;
}

export default function KnowledgePage() {
  const { kbs, docs, tasks, navigate, selectedKbId, setSelectedKbId, notify, refresh } = useApp();
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');
  const [editing, setEditing] = useState<KnowledgeBase | null | undefined>(undefined);
  const [importing, setImporting] = useState(false);
  const [form] = Form.useForm();
  const kb = kbs.find(k => k.id === selectedKbId);
  const shown = kbs.filter(k => (category === 'all' || k.category === category) && `${k.name}${k.description}${k.tags.join('')}`.toLowerCase().includes(search.toLowerCase()));

  function openEdit(item: KnowledgeBase | null) {
    setEditing(item);
    form.setFieldsValue(item || { name: '', description: '', category: '行政制度', tags: [], color: 'violet',embedding:'' });
  }
  async function saveLibrary() {
    let values;
    try { values = await form.validateFields(); } catch { return; }
    if (kbs.some(k => k.name === values.name.trim() && k.id !== editing?.id)) { form.setFields([{ name: 'name', errors: ['已有同名知识库，请换一个名称'] }]); return; }
    try {
      await api(editing ? `/knowledge-bases/${editing.id}` : '/knowledge-bases',json(editing?'PATCH':'POST',values));
      await refresh();setEditing(undefined);notify(editing?'知识库信息已更新':'知识库已创建，可以导入资料');
    } catch(e){notify((e as Error).message,'error')}
  }

  function removeLibrary(item:KnowledgeBase){Modal.confirm({title:`删除“${item.name}”？`,content:isPrototype?'仅删除当前浏览器中的原型副本，已上传原件和后端记录保持不变。':'文档、知识片段与原件将被移除，此操作不能撤销。',okText:'删除知识库',okButtonProps:{danger:true},cancelText:'保留',onOk:async()=>{try{await api(`/knowledge-bases/${item.id}`,{method:'DELETE'});await refresh();setSelectedKbId('');notify('知识库已删除')}catch(e){notify((e as Error).message,'error')}}})}


  if (kb) return <>
    <LibraryDetail kb={kb} onEdit={() => openEdit(kb)} onImport={() => setImporting(true)} />
    <LibraryForm editing={editing} form={form} onCancel={() => setEditing(undefined)} onSave={saveLibrary} />
    <ImportWizard open={importing} kb={kb} onClose={() => setImporting(false)} />
  </>;

  return <div className="knowledge-page page-content">
    <PageTitle eyebrow="YOUR TEAM'S KNOWLEDGE, CONNECTED" title="知识库" description="把分散的资料，变成团队随时可用的知识。" actions={<Button type="primary" size="large" icon={<Plus size={17} />} onClick={() => openEdit(null)}>新建知识库</Button>} />
    <div className="knowledge-intro"><div className="intro-orbit"><Layers3 size={25} /></div><div><strong>从文档到答案，让知识流动起来</strong><p>导入资料、检查知识片段，再通过对话找到有依据的答案。</p></div><button className="intro-link" onClick={() => navigate('chat')}>试试在线对话 <ArrowRight size={16} /></button><div className="intro-decoration" aria-hidden="true"><span /><span /><span /></div></div>
    <div className="knowledge-toolbar"><div className="kb-category-tabs" role="group" aria-label="知识库分类">{['all', '行政制度', '产品知识', '技术研发'].map(c => <button className={category === c ? 'active' : ''} key={c} onClick={() => setCategory(c)}>{c === 'all' ? <>全部知识库 <span>{kbs.length}</span></> : c}</button>)}<Select aria-label="更多知识库分类" placeholder="更多分类" value={['人力资源', '客户服务', '市场运营'].includes(category) ? category : undefined} onChange={setCategory} allowClear onClear={() => setCategory('all')} options={['人力资源', '客户服务', '市场运营'].map(v => ({ label: v, value: v }))} variant="borderless" /></div><Input className="library-search" prefix={<Search size={16} />} placeholder="搜索知识库" value={search} onChange={e => setSearch(e.target.value)} allowClear aria-label="搜索知识库" /></div>
    {shown.length ? <div className="knowledge-grid">{shown.map(item => { const items = docs.filter(d => d.kbId === item.id); const ready = items.filter(d => d.status === 'ready'); const running = tasks.some(t => t.kbId === item.id && t.status === 'processing'); return <article className="knowledge-card" key={item.id}>
      <div className="kb-card-top"><LibraryMark color={item.color} /><Dropdown trigger={['click']} menu={{ items: [{ key: 'edit', label: '编辑知识库', icon: <Pencil size={14} /> }, { key: 'delete', label: '删除知识库', icon: <Trash2 size={14} />, danger: true }], onClick: ({ key }) => key === 'edit' ? openEdit(item) : removeLibrary(item) }}><Button type="text" aria-label={`${item.name}操作`} icon={<Ellipsis size={19} />} /></Dropdown></div>
      <button className="kb-card-body" onClick={() => navigate('knowledge', item.id)}><h2>{item.name}<ChevronRight size={18} /></h2><p>{item.description}</p></button>
      <div className="kb-tags">{item.tags.map(t => <span key={t}>{t}</span>)}</div>
      <div className="kb-card-stats"><span><Files size={14} />{items.length} 份文档</span><span><Layers3 size={14} />{formatNumber(ready.reduce((n, d) => n + (d.chunkCount ?? d.chunks.length), 0))} 个片段</span></div>
      <div className="kb-card-footer"><StatusPill status={running ? 'indexing' : ready.length ? 'ready' : 'empty'} /><span>{item.updatedAt} 更新</span></div>
    </article>; })}<button className="new-library-card" onClick={() => openEdit(null)}><span><Plus size={25} /></span><strong>创建新的知识库</strong><p>让更多团队知识，在这里汇集</p></button></div> : <EmptyState icon={<Search size={28} />} title="没有找到匹配的知识库" description="试试其他关键词，或查看全部分类。" action={<Button onClick={() => { setSearch(''); setCategory('all'); }}>查看全部</Button>} />}
    <div className="knowledge-footer-note"><ShieldCheck size={15} /><span>支持 Word、PDF、Markdown、图片及表格。扫描页与复杂图文需配置云解析和视觉模型。</span></div>
    <LibraryForm editing={editing} form={form} onCancel={() => setEditing(undefined)} onSave={saveLibrary} />
  </div>;
}

function LibraryForm({ editing, form, onCancel, onSave }: { editing: KnowledgeBase | null | undefined; form: ReturnType<typeof Form.useForm>[0]; onCancel: () => void; onSave: () => void | Promise<void> }) {
  const {models}=useApp();
  return <Modal title={editing ? '编辑知识库' : '新建知识库'} open={editing !== undefined} onCancel={onCancel} onOk={() => { void Promise.resolve(onSave()).catch(() => {}); }} okText={editing ? '保存修改' : '创建知识库'} cancelText="取消" forceRender width={520}>
    <Form form={form} layout="vertical" className="kb-edit-form"><Form.Item name="name" label="知识库名称" rules={[{ required: true, whitespace: true, message: '请输入知识库名称' }, { max: 30, message: '名称最多 30 个字' }]}><Input placeholder="如：企业制度手册" maxLength={30} showCount /></Form.Item><Form.Item name="description" label="说明" rules={[{ max: 120, message: '说明最多 120 个字' }]}><Input.TextArea rows={3} placeholder="告诉团队，这个知识库可以解答哪些问题" maxLength={120} showCount /></Form.Item><div className="form-two-columns"><Form.Item name="category" label="分类"><Select options={categories.map(c => ({ value: c, label: c }))} /></Form.Item><Form.Item name="color" label="标识颜色"><Select options={[['violet', '鸢尾紫'], ['blue', '天空蓝'], ['teal', '薄荷绿'], ['orange', '暖杏橙'], ['pink', '蔷薇粉'], ['slate', '岩石灰']].map(([value, label]) => ({ value, label }))} /></Form.Item></div><Form.Item name="tags" label="标签"><Select mode="tags" maxCount={3} tokenSeparators={[',', '，']} placeholder="输入标签，按回车添加" /></Form.Item><Form.Item name="embeddingConfigId" label="向量模型"><Select allowClear placeholder="可稍后在知识库配置中选择" options={models.filter(m=>m.type==='Embedding').map(m=>({value:m.id,label:`${m.name} · ${m.modelId}`}))}/></Form.Item></Form>
  </Modal>;
}

function LibraryDetail({ kb, onEdit, onImport }: { kb: KnowledgeBase; onEdit: () => void; onImport: () => void }) {
  const { docs, notify, navigate, tasks, refresh } = useApp();
  const [tab, setTab] = useState('documents');
  const [docSearch, setDocSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [selection, setSelection] = useState<React.Key[]>([]);
  const [query, setQuery] = useState('');
  const [retrieval, setRetrieval] = useState<Match[] | null>(null);
  const [testing, setTesting] = useState(false);
  const retrievalTimer = useRef<number | null>(null);
  const retrievalRun = useRef(0);
  const [topK, setTopK] = useState(5);
  const [minScore, setMinScore] = useState(0.3);
  const [rerank, setRerank] = useState(true);
  const [mode, setMode] = useState('hybrid');
  const [keywordTag, setKeywordTag] = useState('');
  const [embedding, setEmbedding] = useState(kb.embeddingConfigId||kb.embedding);
  const [configName, setConfigName] = useState(kb.name);
  const [configDescription, setConfigDescription] = useState(kb.description);
  const { models } = useApp();
  useEffect(() => { setTab('documents'); setRetrieval(null); setTesting(false); setSelection([]); setDocSearch(''); setConfigName(kb.name); setConfigDescription(kb.description); setEmbedding(kb.embeddingConfigId||kb.embedding); }, [kb.id]);
  useEffect(() => {
    if (tab !== 'retrieval') setTesting(false);
    return () => {
      retrievalRun.current += 1;
      if (retrievalTimer.current !== null) window.clearTimeout(retrievalTimer.current);
      retrievalTimer.current = null;
    };
  }, [kb.id, tab]);
  const items = docs.filter(d => d.kbId === kb.id);
  const visible = items.filter(d => d.name.toLowerCase().includes(docSearch.toLowerCase()) && (status === 'all' || d.status === status));
  const preview = docs.find(d => d.id === previewId);
  const readyCount = items.filter(d => d.status === 'ready').length;
  async function removeDocs(ids:string[]){try{for(const id of ids)await api(`/documents/${id}`,{method:'DELETE'});await refresh();setSelection([]);notify(`已删除 ${ids.length} 份文档`)}catch(e){notify((e as Error).message,'error')}}
  async function toggleDoc(d:KnowledgeDoc){try{await api(`/documents/${d.id}`,json('PATCH',{status:d.status==='disabled'?'ready':'disabled'}));await refresh();notify(d.status==='disabled'?'文档已启用':'文档已停用，不再参与检索')}catch(e){notify((e as Error).message,'error')}}
  async function rebuildDoc(d:KnowledgeDoc){try{await api(`/documents/${d.id}/reindex`,{method:'POST'});await refresh();notify('已加入重建队列，原发布版本继续服务')}catch(e){notify((e as Error).message,'error')}}
  async function testRetrieval(){const q=query.trim();if(!q){notify('先输入一个检索问题','warning');return}setTesting(true);setRetrieval(null);try{const body:Record<string,unknown>={query:q,topK,minScore,rerank,mode};const tag=keywordTag.trim();if(tag)body.keywordsAny=[tag];const response=await api(`/knowledge-bases/${kb.id}/retrieve`,json('POST',body));setRetrieval(response.results);await refresh()}catch(e){notify((e as Error).message,'error')}finally{setTesting(false)}}
  async function saveConfig(){if(!configName.trim()){notify('知识库名称不能为空','warning');return}const model=models.find(m=>m.type==='Embedding'&&(m.id===embedding||m.modelId===embedding));const save=async()=>{try{await api(`/knowledge-bases/${kb.id}`,json('PATCH',{name:configName.trim(),description:configDescription,embeddingConfigId:model?.id||null,embedding:model?.modelId||embedding}));await refresh();notify('知识库配置已保存，模型变更将重建索引')}catch(e){notify((e as Error).message,'error')}};if(embedding!==(kb.embeddingConfigId||kb.embedding)&&items.length)Modal.confirm({title:'更换向量模型并重建索引？',content:'不同模型向量不可混用，新索引完成前保留旧版本。',okText:'确认更换',cancelText:'取消',onOk:save});else await save()}
  return <div className="library-detail page-content">
    <button className="back-link" onClick={() => navigate('knowledge')}><ArrowLeft size={16} />全部知识库</button>
    <div className="library-detail-heading"><LibraryMark color={kb.color} /><div><h1>{kb.name}</h1><p>{kb.description}</p></div><div className="library-detail-actions"><Button icon={<Settings2 size={15} />} onClick={onEdit}>编辑信息</Button><Button type="primary" icon={<CloudUpload size={17} />} onClick={onImport}>导入知识</Button></div></div>
    <div className="library-detail-meta"><span><Files size={14} />{items.length} 份文档</span><span><Layers3 size={14} />{items.filter(d => d.status === 'ready').reduce((n, d) => n + (d.chunkCount ?? d.chunks.length), 0)} 个可用片段</span><span><Database size={14} />{kb.embedding}</span><StatusPill status={readyCount ? 'ready' : 'empty'} /></div>
    <Tabs className="library-tabs" activeKey={tab} onChange={setTab} items={[
      { key: 'documents', label: <span><Files size={16} />文档管理</span>, children: <>
        <div className="document-toolbar"><div className="document-toolbar-left"><Input prefix={<Search size={15} />} placeholder="搜索文档名称" value={docSearch} onChange={e => setDocSearch(e.target.value)} allowClear aria-label="搜索文档名称" /><Select aria-label="筛选文档状态" value={status} onChange={setStatus} options={[{ value: 'all', label: '全部状态' }, { value: 'ready', label: '可用于问答' }, { value: 'review', label: '待检查' }, { value: 'indexing', label: '构建中' }, { value: 'failed', label: '处理失败' }, { value: 'disabled', label: '已停用' }]} /></div><div className="document-toolbar-right">{selection.length > 0 && <Popconfirm title={`删除选中的 ${selection.length} 份文档？`} description="删除后将不再参与知识库问答。" onConfirm={() => removeDocs(selection as string[])} okText="删除" cancelText="取消"><Button danger icon={<Trash2 size={14} />}>删除选中 ({selection.length})</Button></Popconfirm>}<span>{visible.length} 份文档</span></div></div>
        <div className="document-table"><Table<KnowledgeDoc> rowKey="id" dataSource={visible} rowSelection={{ selectedRowKeys: selection, onChange: setSelection }} pagination={visible.length > 8 ? { pageSize: 8, showSizeChanger: false } : false} scroll={{ x: 790 }} locale={{ emptyText: <EmptyState icon={<FolderOpen size={28} />} title={items.length ? '没有匹配的文档' : '知识库已准备好，导入第一份资料吧'} description="支持 Word、PDF、Markdown、图片和表格。" action={<Button type="primary" icon={<CloudUpload size={15} />} onClick={onImport}>导入知识</Button>} /> }} columns={[
          { title: '文档名称', dataIndex: 'name', width: 310, render: (_, d) => <button className="document-name" onClick={() => setPreviewId(d.id)}><FileIcon kind={d.kind} /><span><strong>{d.name}</strong><small>{d.size} · v{d.version}</small></span></button> },
          { title: '状态', dataIndex: 'status', width: 135, render: s => <StatusPill status={s} /> },
          { title: '知识片段', width: 100, render: (_, d) => (d.chunkCount ?? d.chunks.length) || '—' },
          { title: '更新时间', dataIndex: 'updatedAt', width: 125 },
          { title: '操作', width: 125, fixed: 'right', render: (_, d) => <Space size={3}><Button type="link" onClick={() => setPreviewId(d.id)}>查看</Button><Dropdown trigger={['click']} menu={{ items: [{ key: 'toggle', label: d.status === 'disabled' ? '启用文档' : '停用文档', disabled: !['ready', 'disabled'].includes(d.status) }, { key: 'rebuild', label: '重新索引', disabled: d.status === 'indexing' }, { key: 'delete', label: '删除文档', danger: true }], onClick: ({ key }) => { if (key === 'toggle') toggleDoc(d); if (key === 'rebuild') rebuildDoc(d); if (key === 'delete') Modal.confirm({ title: `删除“${d.name}”？`, content: '文档及其知识片段将从知识库移除。', okText: '删除', okButtonProps: { danger: true }, cancelText: '取消', onOk: () => removeDocs([d.id]) }); } }}><Button type="text" size="small" aria-label={`${d.name}更多操作`} icon={<Ellipsis size={17} />} /></Dropdown></Space> }
        ]} /></div><div className="detail-bottom-note"><ShieldCheck size={14} />停用或删除的文档不参与检索。上传完成后，需要索引成功才能用于问答。<button onClick={() => navigate('tasks')}>查看处理任务 <ArrowRight size={13} /></button></div>
      </> },
      { key: 'retrieval', label: <span><FileSearch size={16} />检索测试</span>, children: <div className="retrieval-layout"><SectionCard title="先检索，再验证" subtitle="用一个真实问题，检查知识片段是否能被找到。"><div className="retrieval-form"><label htmlFor="retrieval-query">测试问题</label><Input.TextArea id="retrieval-query" rows={4} value={query} onChange={e => setQuery(e.target.value)} placeholder="例如：出差的住宿费用标准是多少？" maxLength={1000} /><div className="retrieval-examples">试试：{['住宿费用标准', '报销审批流程', '火星基地建设'].map(q => <button onClick={() => setQuery(q)} key={q}>{q}</button>)}</div><Form layout="vertical"><Form.Item label="检索模式"><Select value={mode} onChange={setMode} options={[{ value: 'hybrid', label: '混合检索（推荐）' }, { value: 'semantic', label: '语义检索' }, { value: 'keyword', label: '关键词检索' }]} /></Form.Item><Form.Item label="关键词筛选（可选）"><Input value={keywordTag} onChange={e => setKeywordTag(e.target.value)} placeholder="按文档元数据关键词过滤，如：出差" allowClear aria-label="关键词筛选" /></Form.Item><div className="form-two-columns"><Form.Item label="返回片段数"><InputNumber min={1} max={20} value={topK} onChange={v => setTopK(v || 1)} style={{ width: '100%' }} /></Form.Item><Form.Item label="结果重排"><Switch checked={rerank} onChange={setRerank} checkedChildren="开启" unCheckedChildren="关闭" /></Form.Item></div><Form.Item label={`最低相关度 ${minScore.toFixed(2)}`}><Slider min={0} max={1} step={.05} value={minScore} onChange={setMinScore} /></Form.Item></Form><Button type="primary" block icon={<Search size={16} />} loading={testing} onClick={testRetrieval}>开始检索测试</Button><p className="retrieval-simulation-note">后端按当前库已发布文档执行检索与重排。相似度和排序分数不是答案正确率。</p></div></SectionCard><SectionCard title="命中的知识片段" subtitle={retrieval ? `共 ${retrieval.length} 条 · 仅展示当前库可用文档` : '检索结果和原文位置将在这里展示'}>{testing ? <div className="retrieval-loading"><LoaderCircle className="spin" size={28} /><p>正在查找相关知识…</p></div> : retrieval === null ? <EmptyState icon={<FileSearch size={34} />} title="看看知识能否回答你的问题" description="输入测试问题，检查命中内容、排序和来源位置。" /> : retrieval.length === 0 ? <EmptyState icon={<Search size={32} />} title="当前知识库未找到足够依据" description="可尝试更具体的关键词，或检查相关文档是否已经索引完成。" /> : <div className="retrieval-results">{retrieval.map(({ doc, chunk, score }, i) => <article key={`${doc.id}-${chunk.id}`}><div className="result-card-title"><span className="result-rank">{i + 1}</span><strong>{chunk.title}</strong>{chunk.role === 'child' && <Tag color="blue">子段</Tag>}<Tag color="purple">{score.toFixed(2)}</Tag></div><p>{chunk.content}</p>{chunk.parentContext && <details className="parent-context"><summary>父段上下文</summary><p>{chunk.parentContext}</p></details>}<button className="result-source" onClick={() => setPreviewId(doc.id)}><FileIcon kind={doc.kind} size={14} />{doc.name}<span>{chunk.location}</span><ChevronRight size={14} /></button></article>)}</div>}</SectionCard></div> },
      { key: 'config', label: <span><Settings2 size={16} />知识库配置</span>, children: <div className="kb-config"><SectionCard title="基本信息" subtitle="清晰的名称和说明能帮助团队选择正确的知识库。"><Form layout="vertical"><Form.Item label="知识库名称" required><Input value={configName} onChange={e => setConfigName(e.target.value)} maxLength={30} /></Form.Item><Form.Item label="知识库说明"><Input.TextArea rows={3} value={configDescription} onChange={e => setConfigDescription(e.target.value)} maxLength={120} /></Form.Item></Form></SectionCard><SectionCard title="索引与知识处理" subtitle="更换向量模型需要重建索引，不能混用不同的向量空间。"><Form layout="vertical"><Form.Item label="Embedding 模型"><Select value={embedding} onChange={setEmbedding} options={models.filter(m => m.type === 'Embedding' && m.enabled).map(m => ({ value: m.id, label: `${m.name} · ${m.modelId}` }))} /></Form.Item></Form><div className="config-facts"><div><span>解析服务</span><strong>阿里云 DocMind</strong></div><div><span>图片理解</span><strong>独立视觉模型</strong></div><div><span>分段方式</span><strong>导入时可选递归 / 父子 / 语义切分</strong></div><div><span>知识库标识</span><code>{kb.id}</code></div></div><Alert type="info" showIcon message="图表描述与提取文字分别保存，可打开原件核对来源。" /></SectionCard><div className="config-save"><Button type="primary" onClick={saveConfig}>保存配置</Button></div></div> }
    ]} />
    <DocumentPreview doc={preview || null} onClose={() => setPreviewId(null)} />
  </div>;
}

function DocumentPreview({ doc:summary, onClose }: { doc: KnowledgeDoc | null; onClose: () => void }) {
  const [fullDoc,setFullDoc]=useState<KnowledgeDoc|null>(null);
  const doc=fullDoc?.id===summary?.id?fullDoc:summary;
  useEffect(()=>{let live=true;if(summary)void api(`/documents/${summary.id}`).then(value=>{if(live)setFullDoc(value)}).catch(()=>{if(live)setFullDoc(null)});else setFullDoc(null);return()=>{live=false}},[summary?.id,summary?.version,summary?.updatedAt,summary?.draftStatus]);
  const { publishDoc, notify, refresh } = useApp();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [previewTab, setPreviewTab] = useState('chunks');
  const [metaDraft, setMetaDraft] = useState<DocMetadata>({});
  const [metaBusy, setMetaBusy] = useState(false);
  useEffect(() => { setEditingId(null); setPreviewTab('chunks'); setMetaDraft(doc?.metadata || {}); }, [doc?.id, doc?.metadata?.extractedAt, doc?.updatedAt]);
  async function saveMetadata(){if(!doc)return;setMetaBusy(true);try{await api(`/documents/${doc.id}/metadata`,json('PATCH',{docDate:metaDraft.docDate||null,bizVersion:metaDraft.bizVersion||null,subject:metaDraft.subject||null,ownerPerson:metaDraft.ownerPerson||null,keywords:metaDraft.keywords||[],likelyQuestions:metaDraft.likelyQuestions||[]}));await refresh();setFullDoc(await api(`/documents/${doc.id}`));notify('元数据已保存')}catch(e){notify((e as Error).message,'error')}finally{setMetaBusy(false)}}
  async function reextractMetadata(){if(!doc)return;setMetaBusy(true);try{const res=await api(`/documents/${doc.id}/metadata/extract`,json('POST',{mode:'auto'}));setMetaDraft(res.metadata||{});await refresh();setFullDoc(await api(`/documents/${doc.id}`));notify(res.warnings?.length?'已重新抽取（含提示）':'已重新抽取元数据')}catch(e){notify((e as Error).message,'error')}finally{setMetaBusy(false)}}
  async function saveChunk(){if(!content.trim()||!doc){notify('知识片段内容不能为空','warning');return}try{const chunks=(doc.draftChunks||doc.chunks).map(c=>c.id===editingId?{...c,content,edited:true}:c);await api(`/documents/${doc.id}`,json('PATCH',{chunks}));await refresh();setFullDoc(await api(`/documents/${doc.id}`));setEditingId(null);notify('修订已保存为草稿，请发布后用于问答')}catch(e){notify((e as Error).message,'error')}}
  return <Drawer title={<div className="preview-drawer-title"><FileIcon kind={doc?.kind || 'pdf'} /><span>{doc?.name}<small>文档与知识片段</small></span></div>} width={760} open={!!doc} onClose={onClose} extra={doc ? <StatusPill status={doc.status} /> : undefined}>
    {doc && <>{!!doc.warnings?.length&&<Alert type="warning" showIcon message="解析提示" description={doc.warnings.map((w,i)=><div key={i}>{w}</div>)}/>}<Alert className="preview-demo-alert" type="info" showIcon message={isPrototype?'本地原型副本。已有片段沿用只读快照；新增二进制文件仅展示占位流程，未进行云解析。':'实际解析结果。图像描述由视觉模型生成，重要内容请核对原件。'} /><div className="preview-meta"><span>{doc.size}</span><span>版本 v{doc.version}</span><span>{(doc.draftChunks || doc.chunks).length} 个片段</span><span>{doc.updatedAt}</span></div><Tabs activeKey={previewTab} onChange={setPreviewTab} items={[{ key: 'chunks', label: '知识片段', children: (doc.draftChunks || doc.chunks).length ? <div className="chunk-list">{(doc.draftChunks || doc.chunks).map((c, i) => <article className="chunk-card" key={c.id}><div className="chunk-title"><span className="chunk-number">{String(i + 1).padStart(2, '0')}</span><strong>{c.title}</strong><Tag>{c.kind === 'table' ? '表格' : c.kind === 'image' ? '图像描述' : '文本'}</Tag>{c.role === 'parent' && <Tag color="geekblue">父段</Tag>}{c.role === 'child' && <Tag color="blue">子段</Tag>}{c.edited && <Tag color="orange">已修订</Tag>}<Tooltip title="修订片段"><Button size="small" type="text" aria-label={`修订${c.title}`} icon={<Pencil size={14} />} onClick={() => { setEditingId(c.id); setContent(c.content); }} /></Tooltip></div>{editingId === c.id ? <div className="chunk-editor"><Input.TextArea rows={7} value={content} onChange={e => setContent(e.target.value)} aria-label="修订知识片段内容" /><Space><Button type="primary" size="small" onClick={saveChunk}>保存修订</Button><Button size="small" onClick={() => setEditingId(null)}>取消</Button></Space></div> : c.kind === 'table' ? <DemoTable content={c.content} /> : <p className="chunk-content">{c.content}</p>}<div className="chunk-location"><FileSearch size={13} />{c.location}{c.kind === 'image' && <span>由视觉模型生成 · 需核对原图</span>}</div></article>)}</div> : <EmptyState icon={<FileSearch size={30} />} title={doc.status === 'failed' ? '文件解析失败' : '知识片段尚未就绪'} description={doc.error || '请等待处理完成，或在任务中心查看进度。'} /> }, { key:'metadata',label:'元数据',children:<div className="doc-metadata-panel"><Alert type="info" showIcon message="导入时自动抽取的文档级元数据，可编辑后用于检索过滤；与发布次数 version 分开。" /><Form layout="vertical" style={{marginTop:12}}><div className="form-two-columns"><Form.Item label="时间（文档日期）"><Input value={metaDraft.docDate||''} onChange={e=>setMetaDraft(m=>({...m,docDate:e.target.value}))} placeholder="YYYY-MM-DD" /></Form.Item><Form.Item label="业务版本"><Input value={metaDraft.bizVersion||''} onChange={e=>setMetaDraft(m=>({...m,bizVersion:e.target.value}))} placeholder="如 V2.1 / Rev A" /></Form.Item></div><div className="form-two-columns"><Form.Item label="主体信息"><Input value={metaDraft.subject||''} onChange={e=>setMetaDraft(m=>({...m,subject:e.target.value}))} placeholder="适用组织 / 产品 / 业务主体" /></Form.Item><Form.Item label="负责人"><Input value={metaDraft.ownerPerson||''} onChange={e=>setMetaDraft(m=>({...m,ownerPerson:e.target.value}))} placeholder="编制 / 责任人" /></Form.Item></div><Form.Item label="检索关键词"><Select mode="tags" value={metaDraft.keywords||[]} onChange={v=>setMetaDraft(m=>({...m,keywords:v}))} placeholder="输入后回车添加" tokenSeparators={[',','，']} /></Form.Item><Form.Item label="可能被问到的问题"><Select mode="tags" value={metaDraft.likelyQuestions||[]} onChange={v=>setMetaDraft(m=>({...m,likelyQuestions:v}))} placeholder="输入问题后回车" /></Form.Item><div className="preview-meta" style={{marginBottom:12}}><span>抽取状态：{metaDraft.status||'—'}</span><span>模式：{metaDraft.extractor?.mode||'—'}</span>{metaDraft.confidence!=null&&<span>置信度：{metaDraft.confidence}</span>}{metaDraft.extractedAt&&<span>抽取时间：{metaDraft.extractedAt}</span>}</div><Space><Button type="primary" loading={metaBusy} onClick={()=>void saveMetadata()}>保存元数据</Button><Button loading={metaBusy} onClick={()=>void reextractMetadata()}>重新抽取</Button></Space></Form></div>}, { key:'original',label:'原始文件',children:<div>{isPrototype?<Alert type="info" showIcon message="原件保持不变" description="已上传原件保留在原位置，本地原型不读取、下载或修改原件；可在知识片段页签检查已有内容副本。"/>:doc.kind==='pdf'?<iframe title={doc.name} src={`/api/documents/${doc.id}/original`} style={{width:'100%',height:600,border:'1px solid #eee'}}/>:['png','jpg','jpeg'].includes(doc.kind)?<img src={`/api/documents/${doc.id}/original`} alt={doc.name} style={{maxWidth:'100%'}}/>:<Alert type="info" message="此格式可下载原文件后核对，知识片段见旁边页签。"/>}{!isPrototype&&<a href={`/api/documents/${doc.id}/original`} target="_blank" rel="noreferrer">打开 / 下载原文件</a>}</div> }]} />{(doc.status === 'review' || !!doc.draftChunks?.length) && <div className="publish-document-bar"><span>修订内容尚未发布，确认后重新建立索引。</span><Button type="primary" icon={<Check size={15} />} onClick={()=>void publishDoc(doc.id).catch(()=>{})}>确认并发布</Button></div>}<Button className="export-chunks" icon={<ArrowDownToLine size={15} />} disabled={!(doc.draftChunks || doc.chunks).length} onClick={() => downloadText(`${doc.name}-知识片段.md`, `# ${doc.name}\n\n> 提取的知识片段；图像语义描述请核对原图\n\n${(doc.draftChunks || doc.chunks).map(c => `## ${c.title}\n\n${c.content}\n\n来源：${c.location}`).join('\n\n')}`)}>导出知识片段</Button></>}
  </Drawer>;
}

function DemoTable({ content }: { content: string }) { const rows = content.split('\n').filter(r => r.includes('|')).map(r => r.split('|').map(c => c.trim())); return <div className="demo-table-wrap"><table className="demo-table"><thead><tr>{(rows[0] || []).map((c, i) => <th key={i}>{c}</th>)}</tr></thead><tbody>{rows.slice(1).map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody></table><small>表格结构由原文提取，请核对表头、单位和行范围。</small></div>; }

function ImportWizard({ open, kb, onClose }: { open: boolean; kb: KnowledgeBase; onClose: () => void }) {
  const { docs, settings, startImport, navigate, notify } = useApp();
  const [step, setStep] = useState(0);
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const [autoPublish, setAutoPublish] = useState(true);
  const [parser, setParser] = useState('auto');
  const [imageUnderstanding, setImageUnderstanding] = useState(true);
  const [chunkSize, setChunkSize] = useState(600);
  const [chunkStrategy, setChunkStrategy] = useState<'recursive' | 'parent_child' | 'semantic'>('recursive');
  const [parentSize, setParentSize] = useState(2000);
  const [chunkOverlap, setChunkOverlap] = useState(80);
  const [extractMetadata, setExtractMetadata] = useState(true);
  const [previewIndex, setPreviewIndex] = useState(0);
  const [previewChunks, setPreviewChunks] = useState<Chunk[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewWarnings, setPreviewWarnings] = useState<string[]>([]);
  const [previewError, setPreviewError] = useState('');
  const [previewMeta, setPreviewMeta] = useState<{chunkCount?: number; strategy?: string}>({});
  const [previewKey, setPreviewKey] = useState(0);
  const [previewTab, setPreviewTab] = useState<'chunks' | 'docmeta'>('chunks');
  const [docMetaDrafts, setDocMetaDrafts] = useState<Record<string, DocMetadata & {edited?: boolean}>>({});
  const [chunkDrafts, setChunkDrafts] = useState<Record<string, Chunk[]>>({});
  const [metaBusy, setMetaBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const previewSeq = useRef(0);
  const duplicateCount = files.filter(f => f.duplicate).length;
  const activeFile = files[Math.min(Math.max(0, previewIndex), Math.max(0, files.length - 1))];
  const activeName = activeFile?.name || '';
  const activeDocMeta = docMetaDrafts[activeName] || {};
  const displayChunks = chunkDrafts[activeName] || previewChunks;

  useEffect(() => { if (open) { setStep(0); setFiles([]); setErrors([]); setAutoPublish(true); setParser('auto'); setChunkSize(600); setChunkStrategy('recursive'); setParentSize(2000); setChunkOverlap(80); setExtractMetadata(true); setPreviewIndex(0); setPreviewChunks([]); setPreviewWarnings([]); setPreviewError(''); setPreviewMeta({}); setPreviewKey(0); setPreviewTab('chunks'); setDocMetaDrafts({}); setChunkDrafts({}); } }, [open]);

  useEffect(() => {
    if (!open || step !== 2 || !files.length) return;
    const safeIndex = Math.min(Math.max(0, previewIndex), files.length - 1);
    if (safeIndex !== previewIndex) { setPreviewIndex(safeIndex); return; }
    const file = files[safeIndex];
    if (!file?.file) return;
    if (isPrototype) {
      const fake: Chunk[] = [{ id: 'proto-1', title: file.name.replace(/\.[^.]+$/, '') || '片段 1', content: '原型模式示例片段。可在下方编辑块级关键词；live 模式将调用真实切块预览。', location: '原型', kind: 'text', metadata: { keywords: ['原型', '示例'], subject: file.name, likelyQuestions: [`关于「${file.name}」有哪些内容？`], source: 'auto', extractor: 'rules' } }];
      setPreviewChunks(fake);
      setChunkDrafts(prev => prev[file.name] ? prev : { ...prev, [file.name]: fake });
      setPreviewWarnings(['原型模式使用本地启发式假数据；live 模式请调用 POST /api/chunk-preview。']);
      setPreviewError('');
      setPreviewMeta({ chunkCount: 1, strategy: chunkStrategy });
      return;
    }
    const seq = ++previewSeq.current;
    setPreviewLoading(true); setPreviewError(''); setPreviewWarnings([]);
    const form = new FormData();
    form.append('files', file.file, file.name);
    form.append('chunkSize', String(chunkSize));
    form.append('chunkStrategy', chunkStrategy);
    form.append('chunkOverlap', String(Math.min(chunkOverlap, Math.floor(chunkSize / 2))));
    form.append('enhanceKeywords', 'true');
    form.append('extractMetadata', extractMetadata ? 'true' : 'false');
    form.append('extractMetadataMode', extractMetadata ? 'auto' : 'off');
    if (chunkStrategy === 'parent_child') form.append('parentSize', String(Math.max(parentSize, chunkSize)));
    void api<{chunks: Chunk[]; warnings: string[]; chunkCount: number; options: {chunkStrategy?: string}; metadata?: DocMetadata}>('/chunk-preview', {method: 'POST', body: form})
      .then(body => {
        if (seq !== previewSeq.current) return;
        const chunks = (body.chunks || []).map(c => ({ ...c, metadata: { ...(c.metadata || {}), source: (c.metadata as any)?.edited ? 'manual' : ((c.metadata as any)?.source || 'auto') } }));
        setPreviewChunks(chunks);
        setChunkDrafts(prev => {
          const existing = prev[file.name];
          if (existing?.some(c => (c.metadata as any)?.edited)) return prev;
          return { ...prev, [file.name]: chunks };
        });
        setDocMetaDrafts(prev => {
          if (prev[file.name]?.edited) return prev;
          if (!body.metadata) return prev;
          return { ...prev, [file.name]: { ...body.metadata, edited: false } };
        });
        setPreviewWarnings(body.warnings || []);
        setPreviewMeta({chunkCount: body.chunkCount, strategy: body.options?.chunkStrategy || chunkStrategy});
      })
      .catch(e => {
        if (seq !== previewSeq.current) return;
        setPreviewChunks([]);
        setPreviewError((e as Error).message || '切块预览失败');
      })
      .finally(() => { if (seq === previewSeq.current) setPreviewLoading(false); });
  }, [open, step, previewIndex, files, chunkSize, chunkStrategy, parentSize, chunkOverlap, previewKey, extractMetadata]);

  function append(list: PendingFile[]) {
    const existing = new Set(docs.filter(d => d.kbId === kb.id).map(d => d.name.toLowerCase()));
    const batch = [...files]; const msgs: string[] = []; for (const item of list) { if (batch.length >= settings.batchLimit) { msgs.push(`单批最多 ${settings.batchLimit} 份文件，请分批导入`); break; } if (batch.some(f => f.name.toLowerCase() === item.name.toLowerCase())) { msgs.push(`${item.name} 已在待导入列表中`); continue; } batch.push({ ...item, duplicate: existing.has(item.name.toLowerCase()) }); } setFiles(batch); if (msgs.length) setErrors(prev => [...new Set([...prev, ...msgs])]);
  }
  function addFiles(nativeFiles: FileList | File[]) {
    const incoming: PendingFile[] = []; const problems: string[] = [];
    Array.from(nativeFiles).forEach(file => { const kind = file.name.split('.').pop()?.toLowerCase() || ''; if (!allowedKinds.includes(kind)) problems.push(`${file.name}：暂不支持该文件格式`); else if (file.size > settings.fileLimit * 1024 * 1024) problems.push(`${file.name}：超过 ${settings.fileLimit}MB 限制`); else if (!file.size) problems.push(`${file.name}：文件为空`); else incoming.push({ name: file.name, kind, file, size: file.size >= 1024 * 1024 ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(file.size / 1024))} KB` }); });
    setErrors(problems); append(incoming); if (inputRef.current) inputRef.current.value = '';
  }
  function onDrop(e: DragEvent<HTMLDivElement>) { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }
  function next() { if (step === 0 && !files.length) { notify('请先选择要导入的文件', 'warning'); return; } if (step === 0 && duplicateCount) { notify('存在同名文档，请选择替换或跳过重复文件', 'warning'); return; } setStep(s => Math.min(s + 1, 2)); }

  function updateChunkMeta(chunkId: string, patch: Record<string, unknown>) {
    if (!activeName) return;
    setChunkDrafts(prev => {
      const list = (prev[activeName] || displayChunks).map(c => {
        if (c.id !== chunkId) return c;
        const metadata = { ...(c.metadata || {}), ...patch, edited: true, source: 'manual' };
        return { ...c, metadata };
      });
      return { ...prev, [activeName]: list };
    });
  }

  function updateDocMeta(patch: Partial<DocMetadata>) {
    if (!activeName) return;
    setDocMetaDrafts(prev => ({ ...prev, [activeName]: { ...(prev[activeName] || {}), ...patch, edited: true } }));
  }

  async function autoAnnotateCurrent() {
    if (!activeFile) return;
    setMetaBusy(true);
    try {
      if (isPrototype) {
        const chunks = (chunkDrafts[activeName] || displayChunks).map(c => {
          if ((c.metadata as any)?.edited) return c;
          const title = c.title || activeName;
          return { ...c, metadata: { ...(c.metadata || {}), keywords: ['原型', '自动', ...(Array.isArray((c.metadata as any)?.keywords) ? (c.metadata as any).keywords.slice(0, 3) : [])], subject: title, likelyQuestions: [`关于「${title}」有哪些规定？`], source: 'auto', extractor: 'rules', edited: false } };
        });
        setChunkDrafts(prev => ({ ...prev, [activeName]: chunks }));
        if (!docMetaDrafts[activeName]?.edited) {
          setDocMetaDrafts(prev => ({ ...prev, [activeName]: { docDate: null, bizVersion: null, subject: activeName.replace(/\.[^.]+$/, ''), ownerPerson: null, keywords: ['原型', '导入'], likelyQuestions: [`${activeName}讲了什么？`], status: 'ok', extractor: { mode: 'rules' }, edited: false } }));
        }
        notify('已用原型启发式完成自动标注（已修订片段已跳过）');
        return;
      }
      // Doc-level via metadata batch for this file; chunk-level via enhance endpoint
      const form = new FormData();
      form.append('files', activeFile.file, activeFile.name);
      form.append('mode', 'auto');
      const batch = await api<{items: {name: string; metadata: DocMetadata; warnings: string[]}[]}>('/metadata-preview/batch', { method: 'POST', body: form });
      const item = batch.items?.[0];
      if (item?.metadata && !docMetaDrafts[activeName]?.edited) {
        setDocMetaDrafts(prev => ({ ...prev, [activeName]: { ...item.metadata, edited: false } }));
      }
      const warns = [...(item?.warnings || [])];
      const baseChunks = chunkDrafts[activeName] || displayChunks;
      if (baseChunks.length) {
        const enhanced = await api<{chunks: Chunk[]; warnings: string[]}>('/chunk-preview/enhance', json('POST', { fileName: activeName, chunks: baseChunks, force: true, skipEdited: true }));
        setChunkDrafts(prev => ({ ...prev, [activeName]: enhanced.chunks || baseChunks }));
        warns.push(...(enhanced.warnings || []));
      }
      if (warns.length) setPreviewWarnings(warns);
      notify(warns.length ? '自动标注完成（含提示；已修订片段已跳过）' : '自动标注完成（已修订片段已跳过）');
    } catch (e) {
      notify((e as Error).message || '自动标注失败', 'warning');
    } finally {
      setMetaBusy(false);
    }
  }

  async function autoAnnotateAll() {
    if (!files.length) return;
    setMetaBusy(true);
    try {
      if (isPrototype) {
        const nextChunks: Record<string, Chunk[]> = { ...chunkDrafts };
        const nextDocs: Record<string, DocMetadata & {edited?: boolean}> = { ...docMetaDrafts };
        for (const f of files) {
          const list = (nextChunks[f.name] || (f.name === activeName ? displayChunks : [])).map(c => (c.metadata as any)?.edited ? c : { ...c, metadata: { ...(c.metadata || {}), keywords: ['原型', '批量'], subject: c.title || f.name, likelyQuestions: [`关于「${c.title || f.name}」？`], source: 'auto', extractor: 'rules' } });
          if (list.length) nextChunks[f.name] = list;
          if (!nextDocs[f.name]?.edited) nextDocs[f.name] = { subject: f.name.replace(/\.[^.]+$/, ''), keywords: ['原型', '批量'], likelyQuestions: [`${f.name}的要点？`], status: 'ok', extractor: { mode: 'rules' }, edited: false };
        }
        setChunkDrafts(nextChunks); setDocMetaDrafts(nextDocs);
        notify('已批量自动标注（原型假数据；已手改文件/片段已跳过）');
        return;
      }
      const form = new FormData();
      files.forEach(f => form.append('files', f.file, f.name));
      form.append('mode', 'auto');
      const batch = await api<{items: {name: string; metadata: DocMetadata; warnings: string[]}[]}>('/metadata-preview/batch', { method: 'POST', body: form });
      const nextDocs: Record<string, DocMetadata & {edited?: boolean}> = { ...docMetaDrafts };
      const allWarns: string[] = [];
      for (const item of batch.items || []) {
        if (!nextDocs[item.name]?.edited) nextDocs[item.name] = { ...item.metadata, edited: false };
        allWarns.push(...(item.warnings || []).map(w => `${item.name}：${w}`));
      }
      setDocMetaDrafts(nextDocs);
      const nextChunks: Record<string, Chunk[]> = { ...chunkDrafts };
      for (const f of files) {
        const base = nextChunks[f.name] || (f.name === activeName ? displayChunks : []);
        if (!base.length) continue;
        try {
          const enhanced = await api<{chunks: Chunk[]; warnings: string[]}>('/chunk-preview/enhance', json('POST', { fileName: f.name, chunks: base, force: true, skipEdited: true }));
          nextChunks[f.name] = enhanced.chunks || base;
          allWarns.push(...(enhanced.warnings || []).map(w => `${f.name}：${w}`));
        } catch (e) {
          allWarns.push(`${f.name}：块级自动标注失败 — ${(e as Error).message}`);
        }
      }
      setChunkDrafts(nextChunks);
      if (allWarns.length) setPreviewWarnings(allWarns.slice(0, 12));
      notify(allWarns.length ? '批量自动标注完成（含提示；已手改项已跳过）' : '批量自动标注完成（已手改项已跳过）');
    } catch (e) {
      notify((e as Error).message || '批量自动标注失败', 'warning');
    } finally {
      setMetaBusy(false);
    }
  }

  async function submit(){
    if(!files.length||files.some(f=>f.duplicate))return;
    try{
      const draftMetadataByFile: Record<string, DocMetadata> = {};
      const draftChunkMetaByFile: Record<string, {id?: string; index: number; metadata: Record<string, unknown>}[]> = {};
      for (const f of files) {
        const dm = docMetaDrafts[f.name];
        if (dm && (dm.edited || dm.keywords?.length || dm.subject || dm.docDate || dm.bizVersion || dm.ownerPerson || dm.likelyQuestions?.length)) {
          draftMetadataByFile[f.name] = {
            docDate: dm.docDate ?? null,
            bizVersion: dm.bizVersion ?? null,
            subject: dm.subject ?? null,
            ownerPerson: dm.ownerPerson ?? null,
            keywords: dm.keywords || [],
            likelyQuestions: dm.likelyQuestions || [],
          };
        }
        const chunks = chunkDrafts[f.name];
        if (chunks?.length) {
          draftChunkMetaByFile[f.name] = chunks.map((c, index) => ({
            id: c.id,
            index,
            metadata: {
              keywords: Array.isArray((c.metadata as any)?.keywords) ? (c.metadata as any).keywords : [],
              subject: (c.metadata as any)?.subject ?? null,
              likelyQuestions: Array.isArray((c.metadata as any)?.likelyQuestions) ? (c.metadata as any).likelyQuestions : [],
              edited: Boolean((c.metadata as any)?.edited),
            },
          }));
        }
      }
      const options: Record<string, unknown> = {parser, imageUnderstanding, chunkSize, chunkStrategy, chunkOverlap, extractMetadata};
      if (chunkStrategy === 'parent_child') options.parentSize = Math.max(parentSize, chunkSize);
      if (Object.keys(draftMetadataByFile).length) options.draftMetadataByFile = draftMetadataByFile;
      if (Object.keys(draftChunkMetaByFile).length) options.draftChunkMetaByFile = draftChunkMetaByFile;
      const fresh = files.filter(f => !f.replacementFor);
      if (fresh.length) await startImport(kb.id, fresh.map(f => f.file), autoPublish, options);
      for (const f of files.filter(f => f.replacementFor)) {
        const perFileOpts = { ...options } as Record<string, unknown>;
        if (options.draftMetadataByFile) {
          const only = { [f.name]: (options.draftMetadataByFile as any)[f.name] };
          if (only[f.name]) perFileOpts.draftMetadataByFile = only; else delete perFileOpts.draftMetadataByFile;
        }
        if (options.draftChunkMetaByFile) {
          const only = { [f.name]: (options.draftChunkMetaByFile as any)[f.name] };
          if (only[f.name]) perFileOpts.draftChunkMetaByFile = only; else delete perFileOpts.draftChunkMetaByFile;
        }
        await startImport(kb.id, [f.file], autoPublish, { ...perFileOpts, replaceDocumentId: f.replacementFor });
      }
      notify(isPrototype ? '文件已加入本地原型副本，未上传到后端' : '文件已上传，服务端开始解析');
      onClose();
      navigate('tasks');
    } catch(e) {
      notify((e as Error).message, 'error');
    }
  }

  return <Modal className="import-modal" title={<div className="import-modal-title"><CloudUpload size={21} /><div><strong>导入知识</strong><span>添加到「{kb.name}」</span></div></div>} open={open} onCancel={onClose} footer={<div className="import-footer"><span>{files.length} 份文件待导入</span><Space><Button onClick={step ? () => setStep(s => s - 1) : onClose}>{step ? '上一步' : '取消'}</Button>{step < 2 ? <Button type="primary" onClick={next}>下一步<ArrowRight size={15} /></Button> : <Button type="primary" icon={<CloudUpload size={16} />} onClick={() => void submit()}>开始构建知识库</Button>}</Space></div>} width={1080} destroyOnClose>
    <Steps current={step} size="small" items={[{ title: '选择文件' }, { title: '处理设置' }, { title: '预览与确认' }]} />
    {step === 0 && <div className="import-step"><input type="file" multiple accept={allowedKinds.map(k => `.${k}`).join(',')} ref={inputRef} className="visually-hidden" aria-label="选择知识文件" onChange={e => e.target.files && addFiles(e.target.files)} /><div className={`file-drop-zone ${dragging ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}><div className="upload-cloud"><CloudUpload size={35} strokeWidth={1.4} /></div><h3>拖拽文件到这里，或点击选择</h3><p>Word、PDF、Markdown、图片、Excel / CSV；真实模式另支持 PPTX、TXT、HTML、JSON、Notebook 和代码</p><Button onClick={() => inputRef.current?.click()}>选择本地文件</Button><small>单个文件不超过 {settings.fileLimit}MB · 每批最多 {settings.batchLimit} 份</small></div><Alert type="info" showIcon message={isPrototype?'原型导入只用于本机测试。文本可在浏览器读取，PDF、Word、图片和工作簿只创建占位流程，不上传、不调用 OCR 或视觉模型。':'文件会保存到服务端并进行真实解析；云解析及模型调用按所选服务商计费。'} />{errors.length > 0 && <Alert type="warning" showIcon closable onClose={() => setErrors([])} message="部分文件未加入" description={errors.map(e => <div key={e}>{e}</div>)} />}{duplicateCount > 0 && <Alert type="warning" showIcon message={`发现 ${duplicateCount} 份同名文档，请逐份选择替换或跳过`} action={<Button size="small" onClick={() => { setFiles(prev => prev.filter(f => !f.duplicate)); setPreviewIndex(0); }}>跳过重复文件</Button>} />}{files.length > 0 && <div className="pending-file-list">{files.map(f => <div key={f.name}><FileIcon kind={f.kind} size={18} /><span><strong>{f.name}</strong><small>{f.size}</small></span>{f.duplicate ? <><Tag color="orange">已存在</Tag><Button size="small" onClick={()=>{const old=docs.find(d=>d.kbId===kb.id&&d.name.toLowerCase()===f.name.toLowerCase());if(old)setFiles(prev=>prev.map(x=>x.name===f.name?{...x,duplicate:false,replacementFor:old.id}:x))}}>替换为新版本</Button></> : <Tag color={f.replacementFor?'orange':'green'}>{f.replacementFor?'替换新版本':'待导入'}</Tag>}<Button size="small" type="text" aria-label={`移除${f.name}`} icon={<X size={15} />} onClick={() => setFiles(prev => prev.filter(x => x.name !== f.name))} /></div>)}</div>}</div>}
    {step === 1 && <div className="import-step settings-step"><div className="step-intro"><h3>为不同的资料，选择合适的处理方式</h3><p>{isPrototype?'这些设置仅测试交互，不会发起解析服务请求。':'常用设置已为你准备好，复杂 PDF 和图片会使用云端解析。'}</p></div><div className="parser-options"><button className={parser === 'auto' ? 'selected' : ''} onClick={() => setParser('auto')}><Sparkles size={21} /><strong>智能选择 <Tag color="purple">推荐</Tag></strong><p>普通文本本地读取，复杂图文交给 DocMind。</p>{parser === 'auto' && <Check size={17} />}</button><button className={parser === 'cloud' ? 'selected' : ''} onClick={() => setParser('cloud')}><CloudUpload size={21} /><strong>全部云端解析</strong><p>适用于扫描文件、复杂版面或跨页表格。</p>{parser === 'cloud' && <Check size={17} />}</button></div><div className="import-setting-row"><div><strong>理解图片与流程图</strong><p>由独立视觉模型生成图意描述，与提取文字分别保存。</p></div><Switch checked={imageUnderstanding} onChange={setImageUnderstanding} aria-label="理解图片与流程图" /></div><div className="import-setting-row"><div><strong>检查后自动入库</strong><p>批量资料自动建立索引，异常文件单独等待处理。</p></div><Switch checked={autoPublish} onChange={setAutoPublish} aria-label="检查后自动入库" /></div><div className="import-setting-row"><div><strong>自动抽取元数据</strong><p>导入后抽取时间、版本、主体、负责人、关键词与可能问题；失败不阻断入库。有可用 LLM 时可增强，否则仅启发式。预览步可先手改或批量标注。</p></div><Switch checked={extractMetadata} onChange={setExtractMetadata} aria-label="自动抽取元数据" /></div><div className="chunk-size-setting"><div><strong>切块策略</strong><span>{chunkStrategy === 'parent_child' ? '父子切分' : chunkStrategy === 'semantic' ? '语义切分' : '递归字符切分'}</span></div><div className="parser-options" style={{ marginTop: 8 }}><button type="button" className={chunkStrategy === 'recursive' ? 'selected' : ''} onClick={() => setChunkStrategy('recursive')}><strong>递归字符切分</strong><p>沿用现有分段方式，适合多数制度与说明文档。</p>{chunkStrategy === 'recursive' && <Check size={17} />}</button><button type="button" className={chunkStrategy === 'parent_child' ? 'selected' : ''} onClick={() => setChunkStrategy('parent_child')}><strong>父子切分</strong><p>大段保留上下文，小段用于精细召回；检索命中子段时带回父段。本轮不与语义切分叠加。</p>{chunkStrategy === 'parent_child' && <Check size={17} />}</button><button type="button" className={chunkStrategy === 'semantic' ? 'selected' : ''} onClick={() => setChunkStrategy('semantic')}><strong>语义切分</strong><p>调用 LLM 按主题边界切段；需已配置可用模型，可能产生费用。失败或无模型时自动降级为递归切分。</p>{chunkStrategy === 'semantic' && <Check size={17} />}</button></div>{chunkStrategy === 'semantic' && <Alert style={{ marginTop: 8 }} type="warning" showIcon message="语义切分将按文档段落调用大模型，可能计费；未配置模型时任务会降级为递归切分并写入警告，不阻断入库。" />}</div><div className="chunk-size-setting"><div><strong>{chunkStrategy === 'parent_child' ? '子片段长度' : '建议片段长度'}</strong><span>{chunkSize} 字符左右</span></div><Slider min={200} max={1500} step={100} value={chunkSize} onChange={v => { setChunkSize(v); if (parentSize < v) setParentSize(v); }} /><p>{chunkStrategy === 'parent_child' ? '子段用于向量召回，宜短一些。' : chunkStrategy === 'semantic' ? '语义段建议长度；过长段落仍会再切，仅为模型提示约束。' : '优先保留标题、表头和完整语义，长度仅为建议值。'}</p></div>{chunkStrategy === 'parent_child' && <div className="chunk-size-setting"><div><strong>父片段长度</strong><span>{Math.max(parentSize, chunkSize)} 字符左右</span></div><Slider min={Math.max(400, chunkSize)} max={8000} step={100} value={Math.max(parentSize, chunkSize)} onChange={setParentSize} /><p>父段不进向量索引，仅在子段命中后回填上下文。</p></div>}<div className="chunk-size-setting"><div><strong>片段重叠</strong><span>{chunkOverlap} 字符</span></div><Slider min={0} max={Math.max(0, Math.floor(chunkSize / 2))} step={10} value={Math.min(chunkOverlap, Math.floor(chunkSize / 2))} onChange={setChunkOverlap} /><p>相邻片段共享的字符数，过大可能重复召回。</p></div><Alert type="info" showIcon message={isPrototype?'原型中的复杂图文结果会标为占位内容，后续接入真实解析后再验证。':'复杂图文需要可用的 DocMind 与视觉模型；未配置时任务会显示具体失败原因，不会生成替代内容。'} /></div>}
    {step === 2 && <div className="import-step import-step-preview">
      <Alert type="info" showIcon message={isPrototype ? '确认后仅在本地副本中演示导入。可在切块预览中编辑块级/文档级元数据；原型使用本地假数据。' : '确认切块与元数据。块级可改关键词、主题、可能问题；文档级字段在「文档元数据」页签。失败仅提示，不阻断构建。'} />
      {previewWarnings.length > 0 && <Alert type="warning" showIcon message="预览提示" description={previewWarnings.map(w => <div key={w}>{w}</div>)} />}
      {previewError && <Alert type="error" showIcon message="切块预览失败" description={previewError} action={<Button size="small" onClick={() => setPreviewKey(k => k + 1)}>重新预览</Button>} />}
      <div className="import-preview-panel" role="region" aria-label="切块预览">
        <div className="import-preview-panel-head">
          <div>
            <strong>切块预览与元数据</strong>
            <span>按文件编辑片段标注；自动结果标「自动」，手改标「已修订」</span>
          </div>
          <div className="import-preview-panel-actions">
            <span>{previewLoading ? '解析中…' : (previewMeta.chunkCount != null ? `${displayChunks.length || previewMeta.chunkCount} 块 · ${previewMeta.strategy || chunkStrategy}` : `${files.length} 份文件`)}</span>
            <Button size="small" icon={<Sparkles size={13} />} loading={metaBusy} onClick={() => void autoAnnotateCurrent()}>自动抽取</Button>
            <Button size="small" loading={metaBusy} onClick={() => void autoAnnotateAll()}>批量自动标注</Button>
            {!isPrototype && <Button size="small" icon={<RefreshCw size={13} />} loading={previewLoading} onClick={() => setPreviewKey(k => k + 1)}>刷新预览</Button>}
          </div>
        </div>
        <div className="import-preview-layout">
          <div className="import-preview-files" aria-label="待导入文件">
            {files.map((f, i) => <button type="button" key={f.name} className={previewIndex === i ? 'active' : ''} onClick={() => setPreviewIndex(i)}><FileIcon kind={f.kind} size={16} /><span>{f.name}{(docMetaDrafts[f.name]?.edited || chunkDrafts[f.name]?.some(c => (c.metadata as any)?.edited)) ? ' · 已改' : ''}</span></button>)}
          </div>
          <div className="import-chunk-preview" aria-live="polite">
            <Tabs size="small" activeKey={previewTab} onChange={k => setPreviewTab(k as 'chunks' | 'docmeta')} items={[
              { key: 'chunks', label: '切块', children: (
                previewLoading ? (
                  <div className="import-chunk-empty"><LoaderCircle size={22} className="spin" /><strong>正在生成切块预览</strong><p>正在按当前策略解析选中文件…</p></div>
                ) : previewError ? (
                  <div className="import-chunk-empty"><FileSearch size={22} /><strong>切块预览失败</strong><p>{previewError}</p><Button size="small" onClick={() => setPreviewKey(k => k + 1)}>重试</Button></div>
                ) : displayChunks.length ? (
                  <div className="import-chunk-meta-list">{displayChunks.map((c, i) => {
                    const meta = (c.metadata || {}) as Record<string, any>;
                    const edited = Boolean(meta.edited);
                    const keywords = Array.isArray(meta.keywords) ? meta.keywords as string[] : [];
                    const questions = Array.isArray(meta.likelyQuestions) ? meta.likelyQuestions as string[] : [];
                    return (
                      <article key={c.id || i} className="import-chunk-meta-card">
                        <div className="import-chunk-meta-head">
                          <span>片段 {i + 1} · {c.kind === 'table' ? '表格' : c.kind === 'image' ? '图像描述' : '文本'}{c.role ? ` · ${c.role}` : ''}</span>
                          {edited ? <Tag color="orange">已修订</Tag> : (keywords.length || meta.subject ? <Tag color="blue">自动</Tag> : null)}
                        </div>
                        <h4>{c.title || `片段 ${i + 1}`}</h4>
                        {c.kind === 'table' ? <DemoTable content={c.content} /> : <p>{c.content}</p>}
                        <small>{c.location || '位置未知'}</small>
                        <div className="import-chunk-meta-fields">
                          <label>关键词 / tags</label>
                          <Select mode="tags" size="small" value={keywords} onChange={v => updateChunkMeta(c.id, { keywords: v })} placeholder="回车添加关键词" tokenSeparators={[',', '，']} />
                          <label>主题 subject</label>
                          <Input size="small" value={meta.subject || ''} onChange={e => updateChunkMeta(c.id, { subject: e.target.value })} placeholder="片段主题" />
                          <label>可能问题 likelyQuestions</label>
                          <Select mode="tags" size="small" value={questions} onChange={v => updateChunkMeta(c.id, { likelyQuestions: v })} placeholder="回车添加问题" tokenSeparators={[',', '，']} />
                        </div>
                      </article>
                    );
                  })}</div>
                ) : (
                  <div className="import-chunk-empty"><Layers3 size={22} /><strong>{isPrototype ? '原型模式暂无切块列表' : '暂无切块结果'}</strong><p>{isPrototype ? '请点击「自动抽取」生成假数据，或切换 live 模式。' : '请确认文件格式，或返回上一步调整切块策略后重试。'}</p>{!isPrototype && <Button size="small" onClick={() => setPreviewKey(k => k + 1)}>重新预览</Button>}</div>
                )
              )},
              { key: 'docmeta', label: '文档元数据', children: (
                <div className="import-doc-meta-panel">
                  <Alert type="info" showIcon message="文档级字段写入 doc.metadata；与发布次数 version 分开。手改后入库不会被自动抽取覆盖已填字段。" />
                  <Form layout="vertical" size="small" style={{ marginTop: 12 }}>
                    <div className="form-two-columns">
                      <Form.Item label="时间（文档日期）"><Input value={activeDocMeta.docDate || ''} onChange={e => updateDocMeta({ docDate: e.target.value })} placeholder="YYYY-MM-DD" /></Form.Item>
                      <Form.Item label="业务版本"><Input value={activeDocMeta.bizVersion || ''} onChange={e => updateDocMeta({ bizVersion: e.target.value })} placeholder="如 V2.1 / Rev A" /></Form.Item>
                    </div>
                    <div className="form-two-columns">
                      <Form.Item label="主体信息"><Input value={activeDocMeta.subject || ''} onChange={e => updateDocMeta({ subject: e.target.value })} placeholder="适用组织 / 产品 / 业务主体" /></Form.Item>
                      <Form.Item label="负责人"><Input value={activeDocMeta.ownerPerson || ''} onChange={e => updateDocMeta({ ownerPerson: e.target.value })} placeholder="编制 / 责任人" /></Form.Item>
                    </div>
                    <Form.Item label="检索关键词"><Select mode="tags" value={activeDocMeta.keywords || []} onChange={v => updateDocMeta({ keywords: v })} placeholder="输入后回车添加" tokenSeparators={[',', '，']} /></Form.Item>
                    <Form.Item label="可能被问到的问题"><Select mode="tags" value={activeDocMeta.likelyQuestions || []} onChange={v => updateDocMeta({ likelyQuestions: v })} placeholder="输入问题后回车" /></Form.Item>
                    <div className="preview-meta"><span>{activeDocMeta.edited ? '已修订' : (activeDocMeta.status ? `状态：${activeDocMeta.status}` : '未标注')}</span><span>模式：{activeDocMeta.extractor?.mode || '—'}</span></div>
                  </Form>
                </div>
              )},
            ]} />
          </div>
        </div>
      </div>
      <div className="import-summary">
        <span><Check size={14} />{parser === 'auto' ? '智能解析' : '云端解析'}</span>
        <span><Image size={14} />图意理解{imageUnderstanding ? '开启' : '关闭'}</span>
        <span><Layers3 size={14} />{chunkStrategy === 'parent_child' ? `父子切分 · 父${Math.max(parentSize, chunkSize)}/子${chunkSize}` : chunkStrategy === 'semantic' ? `语义切分 · ${chunkSize}` : `递归切分 · ${chunkSize}`}</span>
        <span><Database size={14} />{autoPublish ? '自动发布索引' : '人工检查后发布'}</span>
        <span><Sparkles size={14} />元数据{extractMetadata ? '自动抽取' : '关闭'}{Object.values(docMetaDrafts).some(d => d.edited) || Object.values(chunkDrafts).some(list => list.some(c => (c.metadata as any)?.edited)) ? ' · 含手改草稿' : ''}</span>
      </div>
    </div>}
  </Modal>;
}

export function TasksPage() {
  const { tasks, kbs, docs, cancelTask, retryTask, publishDoc, navigate } = useApp();
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [previewId, setPreviewId] = useState<string | null>(null);
  const visible = tasks.filter(t => (filter === 'all' || t.status === filter) && t.name.toLowerCase().includes(search.toLowerCase()));
  const running = tasks.filter(t => t.status === 'processing').length;
  const failed = tasks.filter(t => t.status === 'failed').length;
  const review = tasks.filter(t => t.status === 'review').length;
  return <div className="tasks-page page-content"><PageTitle eyebrow="KNOWLEDGE IN MOTION" title="处理任务" description="跟踪知识从上传到可用的每一步，异常文件可单独重试。" actions={<Button icon={<BookOpen size={16} />} onClick={() => navigate('knowledge')}>返回知识库</Button>} /><div className="task-stat-grid"><div><span className="task-stat-icon violet"><LoaderCircle size={21} /></span><section><span>正在处理</span><strong>{running}<small>份</small></strong></section></div><div><span className="task-stat-icon teal"><Check size={21} /></span><section><span>已完成</span><strong>{tasks.filter(t => t.status === 'success').length}<small>份</small></strong></section></div><div><span className="task-stat-icon orange"><FileSearch size={21} /></span><section><span>等待检查</span><strong>{review}<small>份</small></strong></section></div><div><span className="task-stat-icon pink"><RefreshCw size={21} /></span><section><span>需要处理</span><strong>{failed}<small>份</small></strong></section></div></div><SectionCard title="导入与构建记录" subtitle={isPrototype?'原型任务记录仅保存在当前浏览器副本。':'处理任务保存在服务端，切换页面后仍会继续。'}><div className="task-filters"><Select aria-label="筛选任务状态" value={filter} onChange={setFilter} options={[{ value: 'all', label: '全部任务' }, { value: 'processing', label: '处理中' }, { value: 'success', label: '已完成' }, { value: 'review', label: '待检查' }, { value: 'failed', label: '处理失败' }, { value: 'cancelled', label: '已取消' }]} /><Input prefix={<Search size={15} />} placeholder="搜索文件名称" allowClear aria-label="搜索任务名称" value={search} onChange={e => setSearch(e.target.value)} /></div><Table rowKey="id" dataSource={visible} pagination={visible.length > 8 ? { pageSize: 8, showSizeChanger: false } : false} scroll={{ x: 820 }} locale={{ emptyText: <EmptyState icon={<CloudUpload size={32} />} title="还没有处理任务" description="从知识库导入文件后，可以在这里查看每个文件的进度。" action={<Button type="primary" onClick={() => navigate('knowledge')}>前往知识库</Button>} /> }} columns={[{ title: '文件 / 知识库', width: 310, render: (_, t) => <div className="document-name"><FileIcon kind={t.name.split('.').pop() || 'pdf'} /><span><strong>{t.name}</strong><small>{kbs.find(k => k.id === t.kbId)?.name || '知识库已删除'}</small></span></div> }, { title: '处理状态', width: 230, render: (_, t) => <div className="task-progress"><StatusPill status={t.status} /><Progress percent={t.progress} size="small" status={t.status === 'failed' ? 'exception' : t.status === 'success' ? 'success' : t.status === 'processing' ? 'active' : 'normal'} /><small>{t.error || t.stage}</small></div> }, { title: '提交时间', dataIndex: 'time', width: 125 }, { title: '操作', width: 180, fixed: 'right', render: (_, t) => <Space size={3}>{t.status === 'processing' ? <Popconfirm title="停止后续处理？" description={isPrototype?'只取消本地模拟任务，不涉及云端调用。':'已经发生的云端调用可能仍有用量。'} okText="停止处理" cancelText="继续处理" onConfirm={() => cancelTask(t.id)}><Button type="text" size="small">取消任务</Button></Popconfirm> : t.status === 'failed' || t.status === 'cancelled' ? <Button type="link" size="small" icon={<RefreshCw size={13} />} onClick={()=>void retryTask(t.id).catch(()=>{})}>重试</Button> : t.status === 'review' ? <Button type="link" size="small" onClick={() => setPreviewId(t.docId)}>检查并发布</Button> : null}<Button type="link" size="small" disabled={!kbs.some(k => k.id === t.kbId)} onClick={() => navigate('knowledge', t.kbId)}>查看知识库</Button></Space> }]} /></SectionCard><div className="knowledge-footer-note"><Clock3 size={15} />{isPrototype?'本地模拟任务 · 不会同步到后端，刷新后可继续查看副本。':'任务已持久化；服务重启后恢复未完成任务，失败文件可单独重试。'}</div><DocumentPreview doc={docs.find(d => d.id === previewId) || null} onClose={() => setPreviewId(null)} /></div>;
}
