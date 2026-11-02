import {isPrototype} from '../mode';
import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Checkbox, Drawer, Dropdown, Input, Modal, Popover, Select, Tag, Tooltip } from 'antd';
import { ArrowRight, BookOpen, Check, ChevronDown, Copy, Download, History, Info, MessageSquare, MoreHorizontal, PanelLeftOpen, Pencil, Plus, RotateCcw, Search, Send, Sparkles, Square, ThumbsDown, ThumbsUp, Trash2, X } from 'lucide-react';
import { useApp } from '../store';
import type { ChatMessage, ChatSession, SourceRef } from '../types';
import { api, json, streamChat } from '../api';
import { downloadText, FileIcon, nowLabel } from '../components/ui';
import './chat.css';

const suggestions = [
  { icon: '01', title: '出差住宿的报销标准是多少？', detail: '从制度中查找费用标准' },
  { icon: '02', title: '报销申请需要经过哪些审批？', detail: '理解流程图中的办理步骤' },
  { icon: '03', title: '出差前需要完成什么准备？', detail: '快速了解相关办理要求' },
];
interface ActiveRun { controller: AbortController; sessionId: string | null; assistantId: string | null; cancelled: boolean; snapshot: ChatSession | null; }

export async function completeChatStream(body: unknown, onEvent: (event: string, data: any) => void, signal: AbortSignal, transport = streamChat) {
  let completed = false;
  await transport(body, (event, data) => {
    if (event === 'done' && data?.session) completed = true;
    onEvent(event, data);
  }, signal);
  if (!signal.aborted && !completed) throw new Error('对话连接在完成前中断，请重试');
}

export default function ChatPage() {
  const app = useApp();
  const { sessions, setSessions, kbs, docs, models, connections, role, selectedKbId, navigate, notify } = app;
  const [activeId, setActiveId] = useState<string | null>(null);
  const [kbIds, setKbIds] = useState<string[]>(() => selectedKbId ? [selectedKbId] : kbs[0] ? [kbs[0].id] : []);
  const [input, setInput] = useState('');
  const [modelConfigId, setModelConfigId] = useState('');
  const [historySearch, setHistorySearch] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [source, setSource] = useState<SourceRef | null>(null);
  const [sourceIndex, setSourceIndex] = useState(0);
  const [sourceGroup, setSourceGroup] = useState<SourceRef[]>([]);
  const [helpOpen, setHelpOpen] = useState(false);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const runRef = useRef<ActiveRun | null>(null);
  const latest = useRef(app); latest.current = app;
  const scrollEnd = useRef<HTMLDivElement>(null);
  const scrollPanel = useRef<HTMLDivElement>(null);
  const autoScroll = useRef(true);
  const inputRef = useRef<React.ComponentRef<typeof Input.TextArea>>(null);
  const [runningSession, setRunningSession] = useState<ChatSession | null>(null);
  const initialSelection = useRef(false);
  const appliedKb = useRef<string | null>(null);
  const active = runningSession?.id === activeId ? runningSession : sessions.find(session => session.id === activeId);
  const messages = active?.messages || [];
  const visibleSessions = sessions.filter(session => session.title.toLowerCase().includes(historySearch.toLowerCase()));
  const availableModel = (type: 'LLM' | 'Embedding' | 'Rerank', boundId?: string) => models.find(model => model.type === type && (!boundId || model.id === boundId || model.modelId === boundId) && model.enabled && model.status === 'connected' && connections.some(connection => (model.connectionId ? connection.id === model.connectionId : connection.provider === model.provider) && connection.enabled && connection.status === 'connected'));
  const llm = availableModel('LLM', modelConfigId || active?.modelConfigId);
  const llmOptions = models.filter(m => m.type === 'LLM' && availableModel('LLM', m.id)).map(m => ({value: m.id, label: `${m.name} · ${m.modelId}`}));
  const boundEmbedding = kbs.find(kb => kbIds.includes(kb.id))?.embeddingConfigId || kbs.find(kb => kbIds.includes(kb.id))?.embedding;
  const embedding = availableModel('Embedding', boundEmbedding);
  const modelReady = !!llm && !!embedding;
  const selectedNames = kbs.filter(kb => kbIds.includes(kb.id)).map(kb => kb.name);
  const readyDocCount = docs.filter(doc => kbIds.includes(doc.kbId) && doc.status === 'ready').length;

  useEffect(() => { if (selectedKbId && selectedKbId !== appliedKb.current && kbs.some(kb => kb.id === selectedKbId) && !runRef.current) { appliedKb.current = selectedKbId; setKbIds([selectedKbId]); setActiveId(null); initialSelection.current = true; } }, [selectedKbId, kbs]);
  useEffect(() => { if (!activeId) setKbIds(ids => { const valid = ids.filter(id => kbs.some(kb => kb.id === id)); if (!initialSelection.current && kbs.length) { initialSelection.current = true; return [kbs[0].id]; } return valid; }); }, [kbs, activeId]);
  useEffect(() => { if (autoScroll.current) scrollEnd.current?.scrollIntoView({ behavior: isRunning ? 'instant' : 'smooth', block: 'end' }); }, [messages.length, messages.at(-1)?.content, isRunning]);

  const replaceSession = (session: ChatSession) => latest.current.setSessions(prev => [session, ...prev.filter(s => s.id !== session.id)]);
  const stopRun = () => {
    const run = runRef.current; if (!run) return;
    run.cancelled = true; run.controller.abort();
    if (run.sessionId) void api(`/chat-sessions/${run.sessionId}/cancel`, { method: 'POST' }).catch(() => {});
    if (run.snapshot) {
      const stopped = { ...run.snapshot, messages: run.snapshot.messages.map(message => message.id === run.assistantId ? { ...message, status: 'cancelled' as const, content: message.content || '已停止生成。' } : message) };
      replaceSession(stopped);
    }
    setRunningSession(null); runRef.current = null; setIsRunning(false);
  };
  const finalizer = useRef(stopRun); finalizer.current = stopRun;
  useEffect(() => () => { const run = runRef.current; if (run) { run.cancelled = true; run.controller.abort(); if (run.sessionId) void api(`/chat-sessions/${run.sessionId}/cancel`, { method: 'POST' }).catch(() => {}); runRef.current = null; } }, []);

  async function sendQuestion(question: string, regenerate = false) {
    const text = question.trim(); if (!text || runRef.current) return;
    if (!kbIds.length) { notify('请先选择知识库', 'warning'); return; }
    if (text.length > 2000) { notify('问题最多 2,000 字，请精简后重试', 'warning'); return; }
    const spaces = new Set(kbs.filter(kb => kbIds.includes(kb.id)).map(kb => kb.embeddingConfigId || kb.embedding));
    if (spaces.size > 1) { notify('请使用相同 Embedding 配置的知识库', 'warning'); return; }
    const run: ActiveRun = { controller: new AbortController(), sessionId: activeId, assistantId: null, cancelled: false, snapshot: null };
    runRef.current = run; setIsRunning(true); setInput(''); autoScroll.current = true;
    const currentSession = latest.current.sessions.find(session => session.id === activeId);
    const existing = regenerate ? (currentSession?.messages || []).slice(0, -1) : currentSession?.messages || [];
    const baseMessages: ChatMessage[] = regenerate ? existing : [...existing, { id: crypto.randomUUID(), role: 'user', content: text }];
    try {
      await completeChatStream({ sessionId: activeId || undefined, kbIds, question: text, regenerate, modelConfigId: llm?.id }, (event, data) => {
        if (run.cancelled || runRef.current !== run) return;
        if (event === 'meta') {
          run.sessionId = data.sessionId; run.assistantId = data.assistantId;
          run.snapshot = { id: data.sessionId, title: currentSession?.title || text.slice(0, 40), kbIds: [...kbIds], updatedAt: nowLabel(), messages: [...baseMessages, { id: data.assistantId, role: 'assistant', content: '' }] };
          replaceSession(run.snapshot); setActiveId(data.sessionId); setRunningSession(run.snapshot);
        }
        if ((event === 'token' || event === 'sources' || event === 'error') && run.snapshot) {
          run.snapshot = { ...run.snapshot, messages: run.snapshot.messages.map(message => message.id === run.assistantId ? { ...message, ...(event === 'token' ? { content: message.content + data.text } : event === 'sources' ? { sources: data } : { status: 'failed' as const, content: message.content || data.message }) } : message) };
          setRunningSession(run.snapshot);
        }
        if (event === 'done' && data.session) {
          run.snapshot = data.session; replaceSession(data.session); setRunningSession(null);
        }
      }, run.controller.signal);
    } catch (error) {
      if (!run.cancelled && (error as Error).name !== 'AbortError') {
        const text = (error as Error).message || '对话连接中断，请重试'; notify(text, 'error');
        if (run.snapshot) { const failed = { ...run.snapshot, messages: run.snapshot.messages.map(m => m.id === run.assistantId ? { ...m, status: 'failed' as const, content: m.content || text } : m) }; replaceSession(failed); }
        setRunningSession(null);
      }
    } finally {
      if (runRef.current === run) { runRef.current = null; setIsRunning(false); }
      void latest.current.refresh();
    }
  }

  function newSession() { stopRun(); setRunningSession(null); setActiveId(null); setInput(''); setHistoryOpen(false); autoScroll.current = true; inputRef.current?.focus(); }
  function openSession(session: ChatSession) { setModelConfigId(session.modelConfigId || ''); stopRun(); setRunningSession(null); setActiveId(session.id); setKbIds(session.kbIds.filter(id => kbs.some(kb => kb.id === id))); setInput(''); setHistoryOpen(false); autoScroll.current = true; }
  function changeKbs(ids: string[]) {
    if (isRunning) return;
    const spaces = new Set(kbs.filter(kb => ids.includes(kb.id)).map(kb => kb.embeddingConfigId || kb.embedding));
    if (spaces.size > 1) { notify('多库对话需要使用相同的 Embedding 配置', 'warning'); return; }
    setKbIds(ids);
  }
  function deleteSession(id: string) { Modal.confirm({ title: '删除这段对话？', content: '已记录的请求日志将按系统保留策略保存。', okText: '删除对话', cancelText: '取消', okButtonProps: { danger: true }, onOk: async () => { if (runRef.current?.sessionId === id) stopRun(); try { await api(`/chat-sessions/${id}`, { method: 'DELETE' }); if (activeId === id) { setActiveId(null); setRunningSession(null); } await latest.current.refresh(); notify('对话已删除'); } catch (e) { notify((e as Error).message, 'error'); } } }); }
  function openSource(item: SourceRef, group: SourceRef[], index: number) { setSource(item); setSourceGroup(group); setSourceIndex(index); }
  async function feedback(messageId: string, value: 'up' | 'down') { if (!activeId) return; const current = messages.find(m => m.id === messageId); try { const session = await api<ChatSession>(`/chat-sessions/${activeId}`, json('PATCH', { messageId, feedback: current?.feedback === value ? null : value })); replaceSession(session); notify('已记录反馈，谢谢'); } catch(e) { notify((e as Error).message, 'error'); } }
  async function renameSession() { if (!renameId || !renameValue.trim()) return; try { const session = await api<ChatSession>(`/chat-sessions/${renameId}`, json('PATCH', { title: renameValue.trim() })); replaceSession(session); setRenameId(null); } catch(e) { notify((e as Error).message, 'error'); } }
  async function copyMessage(message: ChatMessage) { try { await navigator.clipboard.writeText(message.content); setCopiedId(message.id); window.setTimeout(() => setCopiedId(null), 1600); } catch { notify('浏览器未允许复制，可选中文本手动复制', 'warning'); } }
  function exportConversation() { if (!active?.messages.length) { notify('当前没有可以导出的对话', 'info'); return; } downloadText(`${active.title}.md`, `# ${active.title}\n\n${active.messages.map(message => `## ${message.role === 'user' ? '提问' : '回答'}\n\n${message.content}\n\n${message.sources?.map((ref, i) => `[${i + 1}] ${ref.title} · ${ref.location}`).join('\n') || ''}`).join('\n\n')}`, 'text/markdown;charset=utf-8'); }
  const lastUserQuestion = messages.filter(message => message.role === 'user').at(-1)?.content;
  const kbChooser = <div className="chat-kb-popover"><div className="chat-popover-title">选择对话知识库</div><p>可同时选择相同向量模型的知识库</p><Checkbox.Group value={kbIds} onChange={values => changeKbs(values.map(String))}>{kbs.map(kb => <div className="chat-kb-choice" key={kb.id}><Checkbox value={kb.id} aria-label={kb.name} disabled={isRunning}/><span><strong>{kb.name}</strong><small>{docs.filter(doc => doc.kbId === kb.id && doc.status === 'ready').length} 份可用文档 · {kb.embedding}</small></span>{kb.status === 'empty' && <Tag>空库</Tag>}</div>)}</Checkbox.Group>{!kbs.length && <p>尚未创建知识库，请联系知识库管理人员。</p>}</div>;

  return <div className="chat-page">
    <div className={`chat-history ${historyOpen ? 'is-open' : ''}`}>
      <div className="chat-history-title"><span><History size={16}/>对话历史</span><button className="chat-icon-button history-close" aria-label="关闭对话历史" onClick={() => setHistoryOpen(false)}><X size={17}/></button></div>
      <Button type="primary" block icon={<Plus size={16}/>} onClick={newSession}>新建对话</Button>
      <Input aria-label="搜索对话历史" placeholder="搜索对话" prefix={<Search size={15}/>} value={historySearch} onChange={e => setHistorySearch(e.target.value)} allowClear className="chat-history-search"/>
      <div className="chat-history-label">最近对话 <span>{sessions.length}</span></div>
      <div className="chat-session-list">{visibleSessions.length ? visibleSessions.map(session => <div className={`chat-session-item ${session.id === activeId ? 'active' : ''}`} key={session.id}>
        <button className="chat-session-open" onClick={() => openSession(session)}><MessageSquare size={15}/><span>{session.title}<small>{session.updatedAt}</small></span></button>
        <Dropdown trigger={['click']} menu={{ items: [{ key: 'rename', label: '重命名', icon: <Pencil size={14}/> }, { key: 'delete', label: '删除对话', danger: true, icon: <Trash2 size={14}/> }], onClick: ({ key }) => key === 'delete' ? deleteSession(session.id) : (setRenameId(session.id), setRenameValue(session.title)) }}><button className="chat-icon-button" aria-label={`管理对话：${session.title}`}><MoreHorizontal size={16}/></button></Dropdown>
      </div>) : <div className="chat-history-empty"><MessageSquare size={26}/><p>{historySearch ? '没有匹配的对话' : '开始一次提问\n有价值的对话会保留在这里'}</p></div>}</div>
      <div className="chat-history-note"><span className="chat-anonymous-dot"/>匿名会话 · 仅此浏览器可见<small>清除浏览器数据会移除历史记录</small></div>
    </div>
    {historyOpen && <button className="chat-history-backdrop" aria-label="关闭对话历史遮罩" onClick={() => setHistoryOpen(false)}/>}
    <div className="chat-workspace">
      <div className="chat-toolbar"><div className="chat-toolbar-left"><button className="chat-icon-button history-toggle" aria-label="打开对话历史" onClick={() => setHistoryOpen(true)}><PanelLeftOpen size={20}/></button><div><h2>知识对话<span>基于你的企业知识</span></h2><span className="chat-toolbar-subtitle">让每一个问题，都找到有据可循的答案</span></div></div><div className="chat-toolbar-actions"><Tooltip title="对话说明"><button className="chat-icon-button" aria-label="查看对话说明" onClick={() => setHelpOpen(true)}><Info size={18}/></button></Tooltip><Dropdown trigger={['click']} menu={{ items: [{ key: 'export', label: '导出当前对话', icon: <Download size={15}/>, disabled: !messages.length }, { key: 'new', label: '开始新对话', icon: <Plus size={15}/> }], onClick: ({ key }) => key === 'export' ? exportConversation() : newSession() }}><button className="chat-icon-button" aria-label="更多对话操作"><MoreHorizontal size={20}/></button></Dropdown></div></div>
      <div className="chat-context-bar"><Popover trigger="click" placement="bottomLeft" content={kbChooser}><Button className="chat-kb-trigger" disabled={isRunning} icon={<BookOpen size={16}/>}><span>{selectedNames.length ? `${selectedNames[0]}${selectedNames.length > 1 ? ` +${selectedNames.length - 1}` : ''}` : '选择知识库'}</span><ChevronDown size={14}/></Button></Popover><span className="chat-context-count">{readyDocCount} 份可用文档</span>{!isPrototype&&<Select aria-label="选择回答模型" value={llm?.id} disabled={isRunning} placeholder="选择已验证的回答模型" options={llmOptions} onChange={setModelConfigId} style={{minWidth:220}}/>}<span className={`chat-model-status ${modelReady ? '' : 'unavailable'}`}><i/>{llm?.modelId || '模型未就绪'}</span></div>
      {!modelReady && <div className="chat-model-alert"><Alert type="warning" showIcon message="对话模型尚未就绪" description={<span>请启用 LLM，以及所选知识库绑定的 Embedding 模型（{boundEmbedding || '尚未选择'}）。{role === 'admin' ? <button className="chat-inline-link" onClick={() => navigate('models')}>前往模型与服务 <ArrowRight size={12}/></button> : '请联系管理员完成配置。'}</span>}/></div>}
      <div className="chat-messages" ref={scrollPanel} onScroll={() => { const el = scrollPanel.current; if (el) autoScroll.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100; }}>
        {!messages.length ? <div className="chat-welcome"><div className="chat-welcome-emblem"><Sparkles size={33}/><span className="chat-emblem-spark">✦</span></div><div className="chat-welcome-eyebrow">YOUR KNOWLEDGE, CONNECTED</div><h1>你好，有什么可以帮你？</h1><p>从企业知识中寻找答案，让每一份经验发挥价值。<br/>选择知识库，开启一次有依据的对话。</p><div className="chat-suggestions">{suggestions.map(item => <button key={item.icon} onClick={() => sendQuestion(item.title)} disabled={isRunning}><span className="chat-suggestion-number">{item.icon}</span><strong>{item.title}</strong><small>{item.detail}</small><ArrowRight size={16}/></button>)}</div><div className="chat-welcome-foot"><BookOpen size={14}/><span>{readyDocCount ? `已连接 ${readyDocCount} 份已发布文档，回答可查看来源` : '当前没有可用文档，请先导入并发布知识'}</span></div></div> : <div className="chat-thread">{messages.map((message, index) => <div key={message.id} className={`chat-message chat-message-${message.role}`}>
          {message.role === 'user' ? <><div className="chat-user-bubble">{message.content}</div><span className="chat-user-avatar">你</span></> : <><div className="chat-assistant-avatar"><Sparkles size={18}/></div><div className="chat-answer"><div className="chat-answer-byline">密灯助手 <span>知识库问答</span>{message.status === 'cancelled' && <Tag>已停止</Tag>}{message.status === 'failed' && <Tag color="red">未完成</Tag>}</div>{!message.content && isRunning ? <div className="chat-thinking"><span/><span/><span/><small>正在检索知识并组织回答…</small></div> : <div className={`chat-answer-content ${isRunning && index === messages.length - 1 ? 'is-streaming' : ''}`}>{message.content.split('\n\n').map((paragraph, p) => <AnswerParagraph key={p} text={paragraph}/>)}</div>}
          {!!message.sources?.length && message.status !== 'failed' && <div className="chat-answer-sources"><div className="chat-source-heading"><BookOpen size={13}/><span>参考来源</span><small>{message.sources.length} 条引用</small></div>{message.sources.map((ref, i) => <button key={`${ref.docId}-${i}`} onClick={() => openSource(ref, message.sources || [], i)} className="chat-source-chip"><span className="chat-source-index">{i + 1}</span><span>{ref.title}<small>{ref.location}</small></span><ArrowRight size={13}/></button>)}</div>}
          {message.status && <div className="chat-answer-bottom"><div className="chat-answer-actions"><Tooltip title="复制回答"><button className="chat-icon-button" aria-label="复制回答" onClick={() => void copyMessage(message)}>{copiedId === message.id ? <Check size={15}/> : <Copy size={15}/>}</button></Tooltip>{index === messages.length - 1 && lastUserQuestion && <Tooltip title="重新生成"><button disabled={isRunning} className="chat-icon-button" aria-label="重新生成回答" onClick={() => sendQuestion(lastUserQuestion, true)}><RotateCcw size={15}/></button></Tooltip>}<Tooltip title="回答有帮助"><button className={`chat-icon-button ${message.feedback === 'up' ? 'selected' : ''}`} aria-label="回答有帮助" aria-pressed={message.feedback === 'up'} onClick={() => feedback(message.id, 'up')}><ThumbsUp size={15}/></button></Tooltip><Tooltip title="需要改进"><button className={`chat-icon-button ${message.feedback === 'down' ? 'selected' : ''}`} aria-label="回答需要改进" aria-pressed={message.feedback === 'down'} onClick={() => feedback(message.id, 'down')}><ThumbsDown size={15}/></button></Tooltip></div><span className="chat-answer-metrics">{message.duration !== undefined ? `${message.duration.toFixed(2)}s` : ''}{message.tokens != null ? ` · ${message.tokens} 输出 tokens` : ' · 输出用量未知'}</span></div>}
          </div></>}
        </div>)}<div ref={scrollEnd}/></div>}
      </div>
      <div className="chat-composer-area"><div className="chat-composer"><Input.TextArea ref={inputRef} aria-label="输入问题" placeholder={kbIds.length ? '向企业知识提问，例如：出差住宿的报销标准是多少？' : '请先选择知识库'} value={input} onChange={e => setInput(e.target.value)} autoSize={{ minRows: 2, maxRows: 6 }} maxLength={2000} onPressEnter={event => { if (!event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); sendQuestion(input); } }} disabled={isRunning}/><div className="chat-composer-bottom"><span><Sparkles size={14}/>基于知识回答 · 附带参考来源</span><div><small>{input.length > 1600 ? `${input.length}/2000` : 'Enter 发送 · Shift + Enter 换行'}</small>{isRunning ? <Button className="chat-send-button" type="primary" icon={<Square size={15} fill="currentColor"/>} aria-label="停止生成" onClick={stopRun}/> : <Button className="chat-send-button" type="primary" icon={<Send size={17}/>} aria-label="发送问题" disabled={!input.trim()} onClick={() => sendQuestion(input)}/>}</div></div></div><p className="chat-composer-disclaimer">回答基于已发布知识与所配置的云模型，重要信息请核对原文。</p></div>
    </div>
    <Modal title="重命名对话" open={!!renameId} onCancel={() => setRenameId(null)} onOk={() => void renameSession()} okText="保存" cancelText="取消" okButtonProps={{ disabled: !renameValue.trim() }}><Input aria-label="对话名称" autoFocus value={renameValue} onChange={e => setRenameValue(e.target.value)} maxLength={40} onPressEnter={() => void renameSession()}/></Modal>
    <Drawer title={<span className="chat-drawer-heading"><BookOpen size={18}/>知识来源</span>} open={!!source} onClose={() => setSource(null)} width={580} extra={<Tag>当次引用快照</Tag>}>
      {source && <div className="chat-source-detail"><div className="chat-source-document"><FileIcon kind={source.title.split('.').at(-1) || 'pdf'} size={24}/><div><h3>{source.title}</h3><p>{source.location}</p></div></div><div className="chat-source-switch"><span>引用 {sourceIndex + 1} / {sourceGroup.length}</span><div><Button size="small" disabled={sourceIndex <= 0} onClick={() => { const i = sourceIndex - 1; setSourceIndex(i); setSource(sourceGroup[i]); }}>上一条</Button><Button size="small" disabled={sourceIndex >= sourceGroup.length - 1} onClick={() => { const i = sourceIndex + 1; setSourceIndex(i); setSource(sourceGroup[i]); }}>下一条</Button></div></div><Alert type="info" showIcon message="以下为该次回答的引用快照" description={isPrototype?'以下仅为本地副本中的引用展示，原件保持不变，原型不读取原件。':'文档后续更新不会改写历史片段。请打开原文件核对适用范围、版本及上下文。'}/><h4>引用内容</h4><div className="chat-source-quote"><AnswerParagraph text={source.content}/></div>{source.kind === 'image' && <><h4>引用图片</h4>{!isPrototype && source.assetUrl ? <img src={source.assetUrl} className="chat-source-image" alt="知识引用原图"/> : <p className="chat-source-caption">该片段未提供独立图像资产，可打开原文件核对原图。</p>}<p className="chat-source-caption">图像语义描述由视觉模型生成，涉及数值或分支判断时请核对原图。</p></>}<div className="chat-source-metadata"><span>知识类型<strong>{source.kind === 'table' ? '结构化表格' : source.kind === 'image' ? '图像语义描述' : '文本片段'}</strong></span><span>可追溯位置<strong>{source.location}</strong></span><span>引用方式<strong>保留当次片段快照</strong></span></div><Button icon={<Download size={15}/>} onClick={() => downloadText(`${source.title}-引用片段.txt`, `知识引用\n文件：${source.title}\n位置：${source.location}\n\n${source.content}`)}>下载此片段</Button>{!isPrototype&&<Button style={{marginLeft:8}} href={`/api/documents/${encodeURIComponent(source.docId)}/original${source.version ? `?version=${source.version}` : ''}${/\.pdf$/i.test(source.title) && /第\s*(\d+)\s*页/.test(source.location) ? `#page=${source.location.match(/第\s*(\d+)\s*页/)?.[1]}` : ''}`} target="_blank" rel="noreferrer">打开原文件</Button>}{isPrototype&&<p className="chat-source-caption">原件保留在原位置，本地原型不读取或修改原件。</p>}</div>}
    </Drawer>
    <Drawer title="关于知识对话" open={helpOpen} onClose={() => setHelpOpen(false)} width={420}><div className="chat-help"><div className="chat-welcome-emblem"><Sparkles size={28}/></div><h3>答案有来源，知识可追溯</h3><p>选择一个或多个知识库，助手将检索其中已可用的文档，再组织回答。</p><ol><li>多个知识库需使用相同的 Embedding 配置。</li><li>未完成索引、停用及删除的文档不会参与新提问。</li><li>点击来源可查看文件名、位置和引用快照。</li><li>停止生成、重新生成和每次失败均记录独立请求日志。</li></ol><Alert type="info" message={isPrototype?'本地原型模拟对话':'云端模型与知识来源'} description={isPrototype?'对话只用于测试交互，模拟回答不代表模型真实输出，不产生云端用量。':'检索和回答使用管理员配置的服务；供应商未返回的用量显示为未知。停止生成可能仍产生已发生的调用用量。'}/></div></Drawer>
  </div>;
}

function AnswerParagraph({ text }: { text: string }) {
  const lines = text.split('\n');
  const tableLines = lines.filter(line => line.includes('|'));
  const rows = tableLines.map(line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim())).filter(row => !row.every(cell => /^:?-{2,}:?$/.test(cell)));
  if (rows.length >= 2 && rows[0].length >= 2) {
    const other = lines.filter(line => !line.includes('|')).join('\n');
    return <><div className="chat-answer-table-scroll"><table className="chat-answer-table"><thead><tr>{rows[0].map((cell, i) => <th key={i}>{cell}</th>)}</tr></thead><tbody>{rows.slice(1).map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody></table></div>{other && <p className="chat-answer-note">{other}</p>}</>;
  }
  return <p>{text}</p>;
}
