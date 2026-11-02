import baseline from './baseline.empty.json';

/** A deliberately isolated, browser-only transport. No network fallback exists. */
export const PROTOTYPE_STORAGE_KEY = 'zhixu:local-prototype:v1';
type Row = Record<string, any>;
type PrototypeState = Record<string, any>;
type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;
const arrays = ['kbs', 'docs', 'tasks', 'models', 'connections', 'sessions', 'logs', 'applications', 'applicationRuns'];
const secretFields = new Set(['apikey', 'api_key', 'password', 'oldpassword', 'accessid', 'accesssecret', 'access_id', 'access_secret', 'secret', 'encrypted', 'authorization']);
const clone = <T>(value: T): T => structuredClone(value);
const uid = (prefix: string) => `${prefix}-${crypto.randomUUID()}`;
const now = () => new Intl.DateTimeFormat('en-US', {timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false}).format(new Date()).replace(',', '');
const iso = () => new Date().toISOString();
const note = '本地原型模拟';
export class PrototypeError extends Error { constructor(message: string, public status = 400) {super(message); this.name = 'PrototypeError';} }

function clean(value: any): any {
  if (Array.isArray(value)) return value.map(clean);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value).filter(([key]) => !secretFields.has(key.toLowerCase())).map(([key, item]) => [key, clean(item)]));
}
function seedState(seed: Row): PrototypeState {
  const result = clean(clone(seed));
  for (const field of arrays) if (!Array.isArray(result[field])) result[field] = [];
  result.settings = {retention: 30, batchLimit: 20, fileLimit: 50, chatConcurrency: 10, importConcurrency: 2, rerankRequired: false, ...result.settings};
  result.role = 'admin';
  result.schemaVersion = 1;
  if (!result.models.length) {
    const connection = {id: 'prototype-connection', name: '原型示例连接（模拟）', provider: 'OpenRouter', baseUrl: 'https://prototype.invalid/v1', protocol: '本地原型模拟 · 不连接云端', enabled: true, status: 'connected', keyConfigured: false, simulation: true};
    result.connections.push(connection);
    for (const type of ['LLM', 'Embedding', 'Rerank', 'Vision']) result.models.push({id: `prototype-${type.toLowerCase()}`, name: `原型示例${type}模型（模拟）`, modelId: type === 'Embedding' ? 'text-embedding-v4' : `prototype-${type.toLowerCase()}`, provider: 'OpenRouter', connectionId: connection.id, type, enabled: true, status: 'connected', context: 32768, ...(type === 'Embedding' ? {dimension: 1024} : {}), simulation: true});
    for (const kb of result.kbs) {
      const binding = kb.embeddingConfigId || kb.embedding;
      if (binding && !result.models.some((m: Row) => m.type === 'Embedding' && (m.id === binding || m.modelId === binding))) result.models.push({...result.models.find((m: Row) => m.type === 'Embedding'), id: String(binding), modelId: kb.embedding || String(binding), name: '原型示例向量模型（模拟）'});
    }
  }
  return result;
}

export function createPrototypeAdapter(seed: Row, storage?: StorageLike) {
  let state = seedState(seed);
  try {
    const previous = storage?.getItem(PROTOTYPE_STORAGE_KEY);
    if (previous) {
      const parsed = JSON.parse(previous);
      if (parsed.schemaVersion === 1) state = {...state, ...clean(parsed)};
    }
  } catch { /* A damaged prototype copy never affects the server or baseline. */ }
  const persist = () => {
    try {storage?.setItem(PROTOTYPE_STORAGE_KEY, JSON.stringify(clean(state)));}
    catch {throw new PrototypeError('本地原型存储空间不足，请先导出原型草稿或减少原型文件内容', 507);}
  };
  const row = (field: string, id: string): Row => {
    const item = state[field].find((entry: Row) => entry.id === id);
    if (!item) throw new PrototypeError('本地原型中未找到此记录', 404);
    return item;
  };
  const manager = () => {if (!['admin', 'manager'].includes(state.role)) throw new PrototypeError('请在本地原型切换到管理角色', 403);};
  const admin = () => {if (state.role !== 'admin') throw new PrototypeError('请在本地原型切换到管理员', 403);};
  const remove = (field: string, id: string) => {row(field, id); state[field] = state[field].filter((item: Row) => item.id !== id); return {ok: true, message: `${note}：仅移除了原型副本`};};
  const session = () => ({role: state.role, csrf: 'local-prototype-only', authenticated: true, prototype: true});
  const stateView = () => {
    const result = clone(state);
    result.docs = result.docs.map((doc: Row) => ({...doc, chunkCount: (doc.chunks || []).length, hasDraft: Boolean(doc.draftChunks?.length)}));
    result.kbs = result.kbs.map((kb: Row) => ({...kb, status: result.docs.some((doc: Row) => doc.kbId === kb.id && doc.status === 'ready') ? 'ready' : 'empty'}));
    delete result.applicationRuns;
    delete result.applications;
    result.runtime = {database: 'prototype-browser', vectors: 'prototype-keyword', tasks: 'prototype-local', cloudConfigured: false, prototype: true};
    if (state.role === 'user') {result.docs = result.docs.filter((d: Row) => d.status === 'ready'); result.tasks = []; result.logs = [];}
    if (state.role === 'manager') result.logs = result.logs.filter((l: Row) => l.source !== 'chat');
    return result;
  };
  const addLog = (source: string, question: string, answer: string, kbName = '本地原型', steps: Row[] = [], extra: Row = {}) => {
    const id = extra.id || uid('prototype-request');
    const log = {id, traceId: extra.traceId || id, source, question, answer, kbName, model: '本地原型模拟', role: state.role, status: 'success', tokens: null, inputTokens: null, outputTokens: null, duration: 0, firstToken: null, time: now(), steps, simulation: true, ...extra};
    state.logs.unshift(log); return log;
  };
  const retrieve = (kbIds: string[], query: string, topK = 5) => {
    const terms = [...new Set(query.toLowerCase().match(/[a-z0-9]+|[\u4e00-\u9fff]/g) || [])];
    const matches: Row[] = [];
    for (const doc of state.docs.filter((d: Row) => kbIds.includes(d.kbId) && d.status === 'ready')) for (const chunk of doc.chunks || []) {
      const haystack = `${doc.name} ${chunk.title} ${chunk.content}`.toLowerCase();
      const score = terms.filter(t => haystack.includes(t)).length / Math.max(1, terms.length);
      if (score > 0) matches.push({doc: clone(doc), chunk: clone(chunk), score});
    }
    return matches.sort((a, b) => b.score - a.score).slice(0, Math.min(20, Math.max(1, topK)));
  };
  const sourceFor = ({doc, chunk}: Row) => ({docId: doc.id, chunkId: chunk.id, title: doc.name, location: chunk.location || '本地原型副本', content: chunk.content, kind: chunk.kind || 'text', version: doc.version, simulation: true});
  const publishDoc = (doc: Row, operation = 'publish') => {
    doc.chunks = clone(doc.draftChunks || doc.chunks || []); delete doc.draftChunks; delete doc.draftStatus;
    doc.status = 'ready'; doc.version = (doc.version || 0) + 1; doc.chunkCount = doc.chunks.length; doc.updatedAt = now();
    const taskId = uid('prototype-task'); const task = {id: taskId, traceId: taskId, kbId: doc.kbId, docId: doc.id, name: doc.name, status: 'success', progress: 100, stage: `${note}：${operation === 'reindex' ? '索引流程' : '发布流程'}完成，未调用云端`, autoPublish: true, time: now()};
    state.tasks.unshift(task); return task;
  };
  const appVisible = (app: Row) => {
    if (state.role !== 'user') return Object.fromEntries(Object.entries(app).filter(([key]) => key !== 'published'));
    if (!app.published && !app.publishedRevision) throw new PrototypeError('此原型应用尚未发布', 404);
    return {id: app.id, name: app.published?.name || app.name, description: app.published?.description || app.description, status: 'published', revision: app.publishedRevision, publishedRevision: app.publishedRevision, updatedAt: app.publishedAt || app.updatedAt};
  };
  const inspectGraph = (app: Row) => {
    const errors: Row[] = []; const nodes: Row[] = app.nodes || []; const edges: Row[] = app.edges || [];
    const byId = new Map(nodes.map(n => [n.id, n]));
    const incoming = new Map(nodes.map(n => [n.id, [] as Row[]])); const outgoing = new Map(nodes.map(n => [n.id, [] as Row[]]));
    const issue = (message: string, nodeId?: string) => errors.push({message, ...(nodeId ? {nodeId} : {})});
    if (byId.size !== nodes.length) issue('节点 ID 不能重复');
    if (nodes.filter(n => n.kind === 'start').length !== 1 || nodes.filter(n => n.kind === 'output').length !== 1) issue('需要且仅需一个开始节点和一个输出节点');
    for (const edge of edges) {
      if (!byId.has(edge.source) || !byId.has(edge.target)) {issue('连线引用了不存在的节点'); continue;}
      outgoing.get(edge.source)!.push(edge); incoming.get(edge.target)!.push(edge);
    }
    const degrees = new Map(nodes.map(n => [n.id, incoming.get(n.id)!.length]));
    const queue = [...degrees].filter(([, count]) => count === 0).map(([id]) => id); const order: string[] = [];
    while (queue.length) {const id = queue.shift()!; order.push(id); for (const edge of outgoing.get(id) || []) {degrees.set(edge.target, degrees.get(edge.target)! - 1); if (!degrees.get(edge.target)) queue.push(edge.target);}}
    if (order.length !== byId.size) issue('流程存在循环连接');
    const ancestors = new Map(nodes.map(n => [n.id, new Set<string>()]));
    for (const id of order) for (const edge of incoming.get(id) || []) {ancestors.get(id)!.add(edge.source); for (const ancestor of ancestors.get(edge.source) || []) ancestors.get(id)!.add(ancestor);}
    const start = nodes.find(n => n.kind === 'start'); const output = nodes.find(n => n.kind === 'output');
    for (const n of nodes) {
      const cfg = n.config || {}; const ins = incoming.get(n.id)!; const outs = outgoing.get(n.id)!;
      if (n.kind === 'start' && ins.length) issue('开始节点不能有上游', n.id);
      if (n.kind === 'output' && outs.length) issue('输出节点不能有下游', n.id);
      if (n.kind !== 'start' && (!ins.length || start && !ancestors.get(n.id)?.has(start.id))) issue('节点未连接到开始节点', n.id);
      if (n.kind !== 'output' && (!outs.length || output && !ancestors.get(output.id)?.has(n.id))) issue('节点未连接到输出节点', n.id);
      if (n.kind === 'condition' && outs.map(e => e.sourceHandle).sort().join(',') !== 'false,true') issue('条件节点需要“满足”和“不满足”两条分支', n.id);
      if (n.kind === 'llm' && !cfg.modelConfigId) issue('请选择原型模型', n.id);
      if (n.kind === 'knowledge' && !cfg.kbIds?.length) issue('请选择知识库', n.id);
      if (['template', 'output'].includes(n.kind) && !cfg.template?.trim()) issue('请填写文本模板', n.id);
      if (n.kind === 'llm' && !cfg.prompt?.trim()) issue('请填写提示词', n.id);
      if (n.kind === 'condition' && !cfg.value) issue('请填写条件匹配值', n.id);
      for (const field of ['template', 'prompt', 'query', 'source']) for (const match of String(cfg[field] || '').matchAll(/\{\{\s*([^{}]+?)\s*\}\}/g)) {
        const ref = match[1].trim(); if (['input', 'context', 'previous.output'].includes(ref)) continue;
        if (!ref.endsWith('.output') || !ancestors.get(n.id)?.has(ref.slice(0, -7))) issue(`变量 ${ref} 不是可用上游节点`, n.id);
      }
    }
    return {valid: errors.length === 0, errors, order, incoming, outgoing, ancestors, byId};
  };
  const runApplication = (app: Row, body: Row) => {
    if (body.mode === 'draft') manager();
    const definition = body.mode === 'draft' ? app : app.published || (app.publishedRevision ? app : null);
    if (!definition) throw new PrototypeError('请先在本地原型发布应用', 409);
    const graph = inspectGraph(definition); if (!graph.valid) throw new PrototypeError(graph.errors.map(e => e.message).join('；'), 422);
    const outputs: Record<string, string> = {}; const contexts: Record<string, string> = {}; const active = new Set<string>(); const steps: Row[] = []; const sources: Row[] = [];
    const render = (text: string, context: string, previous: string) => String(text || '').replace(/\{\{\s*([^{}]+?)\s*\}\}/g, (_, ref: string) => ({input: String(body.input || ''), context, 'previous.output': previous}[ref.trim()] ?? outputs[ref.trim().replace(/\.output$/, '')] ?? ''));
    for (const id of graph.order) {
      const node = graph.byId.get(id)!; const cfg = node.config || {}; const upstream = (graph.incoming.get(id) || []).filter(e => active.has(e.id));
      if (node.kind !== 'start' && !upstream.length) {steps.push({nodeId: id, label: node.label, kind: node.kind, status: 'skipped', output: '', tokens: null, duration: 0, simulation: true}); continue;}
      const previous = upstream.map(e => outputs[e.source]).filter(Boolean).join('\n\n');
      const context = [...(graph.ancestors.get(id) || [])].map(a => contexts[a]).filter(Boolean).join('\n\n'); let output = '';
      if (node.kind === 'start') output = String(body.input || '');
      else if (node.kind === 'condition') {const input = render(cfg.source || '{{input}}', context, previous); output = String(cfg.operator === 'equals' ? input === cfg.value : cfg.operator === 'not_contains' ? !input.includes(cfg.value) : input.includes(cfg.value));}
      else if (node.kind === 'knowledge') {const matches = retrieve(cfg.kbIds, render(cfg.query || '{{input}}', context, previous), cfg.topK); output = matches.map(m => m.chunk.content).join('\n\n'); contexts[id] = output; sources.push(...matches.map(sourceFor));}
      else if (node.kind === 'llm') output = cfg.requireEvidence && !context ? `${note}：当前原型副本未找到知识依据，未调用模型。` : `${note}：未调用真实模型。\n\n节点「${node.label}」已接收以下内容，供检查流程与提示词：\n${render(cfg.prompt, context, previous).slice(0, 2200)}`;
      else output = render(cfg.template || '{{previous.output}}', context, previous);
      outputs[id] = output;
      steps.push({nodeId: id, label: node.label, kind: node.kind, status: 'success', output, tokens: null, duration: 0, simulation: true});
      for (const edge of graph.outgoing.get(id) || []) if (node.kind !== 'condition' || edge.sourceHandle === output) active.add(edge.id);
    }
    const result = {id: uid('prototype-run'), runId: '', traceId: '', applicationId: app.id, applicationName: definition.name, input: body.input, mode: body.mode || 'published', revision: definition.revision || app.publishedRevision, status: 'success', output: outputs[(definition.nodes || []).find((n: Row) => n.kind === 'output')?.id] || '', sources, steps, tokens: null, duration: 0, createdAt: iso(), finishedAt: iso(), simulation: true, message: `${note}：所有节点在浏览器副本执行，未调用云端`}; result.runId = result.id; result.traceId = result.id;
    state.applicationRuns.unshift(result); return result;
  };

  async function dispatch(path: string, options: RequestInit = {}): Promise<any> {
    const method = (options.method || 'GET').toUpperCase(); const route = path.split('?')[0].replace(/\/$/, '') || '/'; const parts = route.split('/').filter(Boolean).map(decodeURIComponent);
    const data: Row = typeof options.body === 'string' ? JSON.parse(options.body || '{}') : {};
    if (route === '/session' && method === 'GET') return session();
    if (route === '/auth/login' && method === 'POST') {if (!['admin', 'manager', 'user'].includes(data.role)) throw new PrototypeError('请选择原型角色', 422); state.role = data.role; return session();}
    if (route === '/auth/logout' && method === 'POST') {state.role = 'user'; return session();}
    if (route === '/auth/password' && method === 'POST') {admin(); return {ok: true, message: `${note}：未修改真实管理口令`};}
    if (route === '/state' && method === 'GET') return stateView();
    if (route === '/settings') {if (method === 'GET') return state.settings; if (method === 'PATCH') {admin(); state.settings = {...state.settings, ...clean(data)}; return state.settings;}}
    if (route === '/configuration-export' && method === 'GET') {admin(); return {prototype: true, exportedAt: iso(), notice: '仅本地原型配置副本，不含凭证，不会自动同步后端', ...clean(state)};}
    if (parts[0] === 'connections') {
      admin();
      if (parts.length === 1 && method === 'GET') return state.connections;
      if (parts.length === 1 && method === 'POST') {const item = {...clean(data), id: uid('prototype-connection'), enabled: data.enabled !== false, status: 'untested', keyConfigured: Boolean(data.apiKey || data.api_key || data.accessSecret), simulation: true}; state.connections.unshift(item); return item;}
      const item = row('connections', parts[1]);
      if (parts[2] === 'test' && method === 'POST') {item.status = 'connected'; item.simulation = true; return {status: 'connected', message: `${note}：仅验证交互，未发起服务商认证`, connection: item};}
      if (parts.length === 2 && method === 'GET') return item;
      if (parts.length === 2 && method === 'PATCH') {Object.assign(item, clean(data), {simulation: true}); if (data.clearCredentials) item.keyConfigured = false; else if (data.apiKey || data.api_key || data.accessSecret) item.keyConfigured = true; return item;}
      if (parts.length === 2 && method === 'DELETE') return remove('connections', item.id);
    }
    if (parts[0] === 'models') {
      admin();
      if (parts.length === 1 && method === 'GET') return state.models;
      const configure = parts[1] === 'configure' && method === 'POST' || parts[2] === 'configure' && method === 'PATCH';
      if (configure) {
        const existing = parts[2] === 'configure' ? row('models', parts[1]) : null;
        const mode = data.connectionMode || (existing ? 'existing' : 'new'); let connection: Row;
        if (mode === 'existing') connection = row('connections', data.connectionId || existing?.connectionId);
        else {connection = {id: uid('prototype-connection'), name: `${data.name || '原型模型'} · 原型连接`, provider: data.provider || 'OpenRouter', protocol: '本地原型模拟', enabled: true, status: 'untested', keyConfigured: Boolean(data.apiKey || data.api_key), simulation: true}; state.connections.unshift(connection);}
        connection.baseUrl = data.baseUrl || data.base_url || connection.baseUrl || 'https://prototype.invalid/v1';
        if (data.apiKey || data.api_key) connection.keyConfigured = true;
        const allowed = ['name', 'type', 'enabled', 'context', 'dimension', 'maxOutput', 'temperature', 'streamUsage', 'sendDimensions'];
        const fields = Object.fromEntries(allowed.filter(key => data[key] !== undefined).map(key => [key, data[key]]));
        const model: Row = {...existing, ...fields, id: existing?.id || uid('prototype-model'), modelId: data.modelId || data.model || existing?.modelId, provider: connection.provider, connectionId: connection.id, enabled: data.enabled !== false, status: 'untested', simulation: true};
        if (!model.name?.trim() || !model.modelId?.trim() || !model.type) throw new PrototypeError('请填写模型名称、模型 ID 与类型', 422);
        if (existing) Object.assign(existing, model); else state.models.unshift(model);
        return {model, connection, message: `${note}：配置仅保存至当前浏览器，不保留输入的 Key`};
      }
      if (parts.length === 1 && method === 'POST') {const item = {...clean(data), id: uid('prototype-model'), enabled: data.enabled !== false, status: 'untested', simulation: true}; state.models.unshift(item); return item;}
      const item = row('models', parts[1]);
      if (parts[2] === 'test' && method === 'POST') {item.status = 'connected'; item.simulation = true; return {status: 'connected', message: `${note}：能力测试界面已演示，未调用模型`, model: item, usage: null};}
      if (parts.length === 2 && method === 'GET') return item;
      if (parts.length === 2 && method === 'PATCH') {Object.assign(item, clean(data), {simulation: true}); return item;}
      if (parts.length === 2 && method === 'DELETE') return remove('models', item.id);
    }
    if (parts[0] === 'knowledge-bases') {
      if (parts.length === 1 && method === 'GET') return state.kbs;
      if (parts.length === 1 && method === 'POST') {manager(); const item = {...clean(data), id: uid('prototype-kb'), name: data.name, tags: data.tags || [], category: data.category || '其他', color: data.color || 'violet', description: data.description || '', embedding: data.embedding || 'text-embedding-v4', embeddingConfigId: data.embeddingConfigId || 'prototype-embedding', status: 'empty', updatedAt: now(), simulation: true}; state.kbs.unshift(item); return item;}
      const kb = row('kbs', parts[1]);
      if (parts[2] === 'retrieve' && method === 'POST') {manager(); const matches = retrieve([kb.id], data.query || '', data.topK); const log = addLog('retrieval', data.query, `${note}：使用浏览器关键词匹配，未运行向量模型或 Rerank`, kb.name); return {results: matches, sources: matches.map(sourceFor), requestId: log.id, traceId: log.traceId || log.id, log, simulation: true};}
      if (parts[2] === 'documents' && method === 'POST') {
        manager(); const form = options.body; if (!(form instanceof FormData)) throw new PrototypeError('请选择原型文件', 422);
        const files = form.getAll('files') as File[]; if (!files.length) throw new PrototypeError('请选择文件', 422);
        if (files.length > state.settings.batchLimit) throw new PrototypeError('超过原型单批文件数量', 422);
        const tasks: Row[] = [];
        for (const file of files) {
          if (file.size > state.settings.fileLimit * 1024 * 1024) throw new PrototypeError('文件超出设置大小', 422);
          const kind = file.name.split('.').pop()?.toLowerCase() || 'file'; const textBased = ['md', 'csv', 'txt'].includes(kind);
          const content = textBased ? (await file.text()).slice(0, 150000) : `${note}占位：已选择 ${file.name}。这里只验证导入流程，未进行真实 OCR、表格解析或视觉识别。`;
          const chunks = [{id: uid('prototype-chunk'), title: file.name, content, kind: kind === 'csv' ? 'table' : 'text', location: textBased ? '本地原型文件内容' : '原型占位，未真实解析'}];
          const replacement = form.get('replaceDocumentId'); const doc = replacement ? row('docs', String(replacement)) : {id: uid('prototype-doc'), kbId: kb.id, version: 0, chunks: []};
          if (replacement && doc.kbId !== kb.id) throw new PrototypeError('不能替换其他知识库的文件', 422);
          Object.assign(doc, {name: file.name, kind, size: `${Math.max(1, Math.ceil(file.size / 1024))} KB`, draftChunks: chunks, status: doc.chunks?.length ? doc.status : 'review', draftStatus: 'review', updatedAt: now(), simulation: true, warnings: textBased ? [`${note}：文本读取在浏览器完成，未调用云端`] : [content]});
          if (!replacement) state.docs.unshift(doc);
          let task: Row;
          if (form.get('autoPublish') !== 'false') task = publishDoc(doc);
          else {const tid = uid('prototype-task'); task = {id: tid, traceId: tid, kbId: kb.id, docId: doc.id, name: file.name, status: 'review', progress: 100, stage: `${note}：草稿待检查`, autoPublish: false, time: now()}; state.tasks.unshift(task);}
          tasks.push(task); addLog('import', `原型导入：${file.name}`, `${note}：实际上传目录未改变`, kb.name, [], {id: task.traceId || task.id, traceId: task.traceId || task.id, taskId: task.id, documentId: doc.id});
        }
        kb.status = state.docs.some((d: Row) => d.kbId === kb.id && d.status === 'ready') ? 'ready' : 'empty'; return {tasks, message: `${note}：文件仅进入浏览器原型副本`};
      }
      if (parts[2] === 'cancel-rebuild' && method === 'POST') {manager(); return {ok: true, message: `${note}：停止原型重建展示`};}
      if (parts.length === 2 && method === 'GET') return kb;
      if (parts.length === 2 && method === 'PATCH') {manager(); Object.assign(kb, clean(data), {updatedAt: now()}); return kb;}
      if (parts.length === 2 && method === 'DELETE') {manager(); state.docs = state.docs.filter((d: Row) => d.kbId !== kb.id); state.tasks = state.tasks.filter((t: Row) => t.kbId !== kb.id); return remove('kbs', kb.id);}
    }
    if (parts[0] === 'documents') {
      const doc = row('docs', parts[1]);
      if (parts[2] === 'original' && method === 'GET') return {prototype: true, name: doc.name, content: (doc.draftChunks || doc.chunks || []).map((c: Row) => c.content).join('\n\n'), message: '原型展示的是副本片段，真实上传原件没有改变'};
      if (parts.length === 2 && method === 'GET') return doc;
      if (parts.length === 2 && method === 'PATCH') {manager(); if (data.chunks) {doc.draftChunks = clone(data.chunks); doc.draftStatus = 'review';} if (data.status) doc.status = data.status; doc.updatedAt = now(); return doc;}
      if (parts.length === 2 && method === 'DELETE') {manager(); state.tasks = state.tasks.filter((t: Row) => t.docId !== doc.id); return remove('docs', doc.id);}
      if (['publish', 'reindex'].includes(parts[2]) && method === 'POST') {manager(); return publishDoc(doc, parts[2]);}
    }
    if (parts[0] === 'tasks') {manager(); const task = row('tasks', parts[1]); if (method === 'POST' && parts[2] === 'cancel') {task.status = 'cancelled'; task.stage = `${note}：已取消`; return task;} if (method === 'POST' && parts[2] === 'retry') return publishDoc(row('docs', task.docId));}
    if (parts[0] === 'chat-sessions') {
      if (parts.length === 1 && method === 'GET') return state.sessions;
      if (parts.length === 1 && method === 'POST') {const item = {id: uid('prototype-chat'), title: data.title || '新对话', kbIds: data.kbIds || [], messages: [], updatedAt: now()}; state.sessions.unshift(item); return item;}
      const item = row('sessions', parts[1]);
      if (parts[2] === 'cancel' && method === 'POST') return {ok: true};
      if (parts.length === 2 && method === 'GET') return item;
      if (parts.length === 2 && method === 'PATCH') {if (data.title) item.title = data.title; if (data.messageId) {const message = item.messages.find((m: Row) => m.id === data.messageId); if (message) message.feedback = data.feedback;} return item;}
      if (parts.length === 2 && method === 'DELETE') return remove('sessions', item.id);
    }

    if (route === '/chunk-preview' && method === 'POST') {
      manager();
      const name = String(data.fileName || 'preview.md');
      const chunk = {id: 'proto-chunk-1', title: name.replace(/\.[^.]+$/, '') || '片段', content: '原型切块预览占位。可编辑块级关键词；live 模式调用真实 API。', location: '原型', kind: 'text', metadata: {keywords: ['原型', '预览'], subject: name, likelyQuestions: [`关于「${name}」有哪些内容？`], source: 'auto', extractor: 'rules'}};
      return {fileName: name, chunks: [chunk], chunkCount: 1, warnings: ['原型模式返回启发式假数据；请用 live 模式验证 POST /api/chunk-preview。'], options: {chunkStrategy: data.chunkStrategy || 'recursive', enhanceKeywords: true}, metadata: {docDate: null, bizVersion: null, subject: name.replace(/\.[^.]+$/, ''), ownerPerson: null, keywords: ['原型'], likelyQuestions: [`${name}讲了什么？`], status: 'ok', extractor: {mode: 'rules'}}, message: 'prototype stub'};
    }
    if (route === '/chunk-preview/enhance' && method === 'POST') {
      manager();
      const chunks = (data.chunks || []).map((c: Row) => {
        const meta = {...(c.metadata || {})};
        if (meta.edited) return {...c, metadata: meta};
        return {...c, metadata: {...meta, keywords: meta.keywords?.length ? meta.keywords : ['原型', '自动'], subject: meta.subject || c.title, likelyQuestions: meta.likelyQuestions?.length ? meta.likelyQuestions : [`关于「${c.title || '片段'}」？`], source: 'auto', extractor: 'rules'}};
      });
      return {fileName: data.fileName || 'preview.md', chunks, chunkCount: chunks.length, warnings: []};
    }
    if (route === '/metadata-preview/batch' && method === 'POST') {
      manager();
      // FormData file names unavailable in prototype stub — return empty list with warning
      return {items: [], count: 0, warnings: ['原型模式批量元数据预览为占位；请用 live 模式调用 POST /api/metadata-preview/batch。'], message: 'prototype stub'};
    }
    if (parts[0] === 'applications') {
      if (parts.length === 1 && method === 'GET') return state.applications.filter((a: Row) => state.role !== 'user' || a.published || a.publishedRevision).map(appVisible);
      if (parts.length === 1 && method === 'POST') {manager(); const item = {...clean(data), id: uid('prototype-app'), revision: 1, publishedRevision: null, status: 'draft', updatedAt: iso(), hasUnpublishedChanges: true, publishedVersions: []}; state.applications.unshift(item); return appVisible(item);}
      const app = row('applications', parts[1]);
      if (parts.length === 2 && method === 'GET') return appVisible(app);
      if (parts[2] === 'runs' && method === 'GET') {appVisible(app); return state.applicationRuns.filter((run: Row) => run.applicationId === app.id);}
      if (parts[2] === 'run' && method === 'POST') {appVisible(app); return runApplication(app, data);}
      if (parts[2] === 'validate' && method === 'POST') {manager(); const result = inspectGraph(app); return {valid: result.valid, errors: result.errors};}
      if (parts[2] === 'publish' && method === 'POST') {manager(); const validation = inspectGraph(app); if (!validation.valid) throw new PrototypeError(validation.errors.map(e => e.message).join('；'), 422); if (data.requireEval) {if (!Array.isArray(data.evalCases) || !data.evalCases.length) throw new PrototypeError('已开启评测门禁，请提供至少一条评测 Case', 422); const cases = data.evalCases; let passed = 0; const rows = cases.map((c: Row) => {const ok = (c.expectStatus || 'success') === 'success'; if (ok) passed++; return {input: c.input, expectStatus: c.expectStatus || 'success', expectContains: c.expectContains || null, status: 'success', passed: ok, outputPreview: '（原型模拟通过）', error: null, tokens: null};}); const passRate = passed / cases.length; const minPassRate = typeof data.minPassRate === 'number' ? data.minPassRate : 1; const evalReport = {passed, total: cases.length, passRate, cases: rows}; if (passRate < minPassRate) throw new PrototypeError(`评测门禁未通过：通过率 ${(passRate*100).toFixed(0)}% < 要求 ${(minPassRate*100).toFixed(0)}%`, 422); app.lastEvalReport = {...evalReport, at: iso(), gate: 'publish'};} if (app.published) {app.publishedVersions = [...(app.publishedVersions || []), {...clone(app.published), publishedAt: app.publishedAt, immutable: true}].slice(-20);} app.published = {name: app.name, description: app.description, nodes: clone(app.nodes), edges: clone(app.edges), revision: app.revision, scenario: app.scenario, immutable: true}; app.publishedRevision = app.revision; app.publishedAt = iso(); app.status = 'published'; app.hasUnpublishedChanges = false; const visible = appVisible(app); return app.lastEvalReport ? {...visible, evalReport: app.lastEvalReport} : visible;}
      if (parts[2] === 'versions' && method === 'GET') {manager(); return {applicationId: app.id, publishedRevision: app.publishedRevision, current: app.published ? clone(app.published) : null, history: clone(app.publishedVersions || []), count: (app.publishedVersions || []).length + (app.published ? 1 : 0)};}
      if (parts[2] === 'rollback' && method === 'POST') {manager(); const rev = data.revision; const candidates = [...(app.publishedVersions || []), ...(app.published ? [app.published] : [])]; const target = candidates.find((s: Row) => s.revision === rev); if (!target) throw new PrototypeError(`未找到已发布版本 v${rev}`, 404); if (app.published && app.published.revision !== rev) {app.publishedVersions = [...(app.publishedVersions || []), {...clone(app.published), publishedAt: app.publishedAt, immutable: true}].slice(-20);} app.published = {...clone(target), immutable: true}; app.publishedRevision = target.revision; app.publishedAt = iso(); app.status = 'published'; app.hasUnpublishedChanges = true; app.lastRollback = {toRevision: rev, at: iso(), bypassedEvalGate: true}; return appVisible(app);}
      if (parts[2] === 'unpublish' && method === 'POST') {manager(); delete app.published; app.publishedRevision = null; app.status = 'draft'; app.hasUnpublishedChanges = true; return appVisible(app);}
      if (parts.length === 2 && method === 'PATCH') {manager(); if (data.expectedRevision && data.expectedRevision !== app.revision) throw new PrototypeError('原型草稿已经修改，请重新打开', 409); const update = clean(data); delete update.expectedRevision; Object.assign(app, update, {revision: app.revision + 1, updatedAt: iso(), hasUnpublishedChanges: true}); return appVisible(app);}
      if (parts.length === 2 && method === 'DELETE') {manager(); state.applicationRuns = state.applicationRuns.filter((r: Row) => r.applicationId !== app.id); return remove('applications', app.id);}
    }
    if (route === '/logs' && method === 'GET') {manager(); return {items: state.logs, total: state.logs.length};}
    if (parts[0] === 'observability') {
      manager();
      const asTrace = (row: Row, rootType: string, title: string) => ({
        traceId: row.traceId || row.id, rootType, rootId: row.id, title, status: row.status || 'unknown',
        tokens: typeof row.tokens === 'number' ? row.tokens : null, duration: typeof row.duration === 'number' ? row.duration : null,
        time: row.time || String(row.createdAt || '').slice(0, 16).replace('T', ' '), createdAt: row.createdAt, attrs: row,
      });
      const traces: Row[] = [];
      for (const log of state.logs) {
        if (state.role === 'manager' && log.source === 'chat') continue;
        traces.push(asTrace(log, log.source === 'import' ? 'import' : log.source, log.question));
      }
      for (const run of state.applicationRuns) traces.push(asTrace(run, 'application', run.applicationName || '应用运行'));
      for (const task of state.tasks) {
        if (!traces.some(t => t.traceId === (task.traceId || task.id))) traces.push(asTrace(task, 'import', `导入：${task.name}`));
      }
      if (parts[1] === 'overview' && method === 'GET') {
        return {
          requests: traces.length, failed: traces.filter(t => t.status === 'failed').length,
          tokensKnown: traces.reduce((s, t) => s + (t.tokens || 0), 0),
          tokensUnknownCount: traces.filter(t => t.tokens === null).length,
          buildsRunning: state.tasks.filter((t: Row) => t.status === 'processing').length,
          byRootType: traces.reduce((acc: Row, t) => {acc[t.rootType] = (acc[t.rootType] || 0) + 1; return acc;}, {}),
          recent: traces.slice(0, 20),
        };
      }
      if (parts[1] === 'billing' && method === 'GET') {
        const buckets: Row = {};
        for (const log of state.logs) {
          if (state.role === 'manager' && log.source === 'chat') continue;
          const b = buckets[log.source] || (buckets[log.source] = {source: log.source, calls: 0, tokensKnown: 0, tokensUnknownCount: 0});
          b.calls++; if (typeof log.tokens === 'number') b.tokensKnown += log.tokens; else b.tokensUnknownCount++;
        }
        if (state.applicationRuns.length) {
          const b = {source: 'application', calls: state.applicationRuns.length, tokensKnown: 0, tokensUnknownCount: 0};
          for (const run of state.applicationRuns) {if (typeof run.tokens === 'number') b.tokensKnown += run.tokens; else b.tokensUnknownCount++;}
          buckets.application = b;
        }
        return {items: Object.values(buckets), pricingConfigured: false, notice: '原型未配置单价，仅展示已知 token。'};
      }
      if (parts[1] === 'traces' && method === 'GET') {
        const params = new URLSearchParams(path.split('?')[1] || '');
        let items = traces;
        if (params.get('rootType')) items = items.filter(t => t.rootType === params.get('rootType'));
        if (params.get('q')) {const q = params.get('q')!.toLowerCase(); items = items.filter(t => t.traceId.toLowerCase().includes(q) || String(t.title).toLowerCase().includes(q));}
        return {items, total: items.length};
      }
      if (parts[1] === 'traces' && parts[2] && method === 'GET') {
        const id = parts[2];
        const log = state.logs.find((l: Row) => l.id === id || l.traceId === id);
        const run = state.applicationRuns.find((r: Row) => r.id === id || r.traceId === id || r.runId === id);
        const task = state.tasks.find((t: Row) => t.id === id || t.traceId === id);
        if (!log && !run && !task) throw new PrototypeError('追踪不存在', 404);
        const trace = run ? asTrace(run, 'application', run.applicationName) : log ? asTrace(log, log.source === 'import' ? 'import' : log.source, log.question) : asTrace(task, 'import', `导入：${task.name}`);
        const steps = (run?.steps || log?.steps || []).map((s: Row, i: number) => ({
          spanId: s.nodeId || `${id}:step:${i}`, name: s.label || s.name || `step_${i}`, kind: s.kind || 'internal',
          status: s.status || 'unknown', duration: typeof s.duration === 'number' ? s.duration : null, tokens: typeof s.tokens === 'number' ? s.tokens : null, model: s.model, error: s.error,
        }));
        const buildStages = (trace.rootType === 'import') ? ['upload_received','parse','chunk','metadata_extract','index','publish'].map(stage => ({
          stage, status: task?.status === 'success' || log?.status === 'success' ? (stage === 'publish' && task?.status === 'review' ? 'pending' : 'success') : (task?.status === 'failed' && stage === 'parse' ? 'failed' : 'unknown'),
          duration: null, tokens: null, model: null, error: null, attrs: {},
        })) : [];
        return {
          trace, steps, buildStages, input: run?.input ?? log?.question ?? null, output: run?.output ?? log?.answer ?? null,
          error: run?.error || task?.error || null, sources: run?.sources || [], toolCalls: [], skillCalls: [], harnessErrors: [],
          gaps: run ? ['toolCalls：原型无工具运行时', 'skillCalls：原型无 Skill', 'harnessErrors：原型无 Harness'] : [],
        };
      }
      if (parts[1] === 'traces' && parts[2] && parts[3] === 'to-case' && method === 'POST') {
        const id = parts[2];
        const log = state.logs.find((l: Row) => l.id === id || l.traceId === id);
        const run = state.applicationRuns.find((r: Row) => r.id === id || r.traceId === id || r.runId === id);
        const query = (data.query || log?.question || run?.input || '').trim();
        if (!query) return {ok: false, error: '无法从追踪提取问题/输入，请手动填写 query', case: null};
        const item = {id: uid('case'), traceId: id, label: data.label || 'good', query, answer: data.answer || log?.answer || run?.output || null, expectedDocIds: data.expectedDocIds || [], kbId: data.kbId || null, note: data.note || null, createdAt: iso(), importable: {query, expectedDocIds: data.expectedDocIds || [], answer: data.answer || null}};
        state.evalCases = state.evalCases || [];
        state.evalCases.unshift(item);
        return {ok: true, case: item, error: null};
      }
      if (parts[1] === 'eval-cases' && method === 'GET') {
        const items = state.evalCases || [];
        return {items, total: items.length};
      }
    }
    throw new PrototypeError(`本地原型尚未实现此操作：${method} ${route}；已阻止真实后端请求`, 501);
  }

  async function request<T = any>(path: string, options: RequestInit = {}): Promise<T> {
    const before = clone(state);
    try {const result = await dispatch(path, options); if ((options.method || 'GET').toUpperCase() !== 'GET') persist(); return clean(clone(result)) as T;}
    catch (error) {state = before; throw error;}
  }
  async function streamChat(body: Row, onEvent: (event: string, data: any) => void, signal: AbortSignal) {
    if (signal.aborted) return;
    const question = String(body.question || '').trim(); if (!question || !body.kbIds?.length) throw new PrototypeError('请先选择知识库并填写原型问题', 422);
    let chat = body.sessionId ? row('sessions', body.sessionId) : null;
    if (!chat) {chat = {id: uid('prototype-chat'), title: question.slice(0, 40), kbIds: body.kbIds, messages: [], updatedAt: now()}; state.sessions.unshift(chat);}
    if (body.regenerate && chat.messages.at(-1)?.role === 'assistant') chat.messages.pop();
    if (!body.regenerate) chat.messages.push({id: uid('prototype-message'), role: 'user', content: question});
    const matches = retrieve(body.kbIds, question); const sources = matches.map(sourceFor);
    const content = matches.length ? `${note}：以下内容来自浏览器资料副本的关键词匹配，未调用 LLM。\n\n${matches.map((m, i) => `${m.chunk.content}\n[${i + 1}]`).join('\n\n')}` : `${note}：当前资料副本未找到匹配片段。此处用于调整提问、回答和来源界面，未调用真实模型。`;
    const message: Row = {id: uid('prototype-message'), role: 'assistant', content: '', sources, tokens: null, duration: 0}; chat.messages.push(message);
    const requestId = uid('prototype-request'); onEvent('meta', {sessionId: chat.id, assistantId: message.id, requestId, traceId: requestId}); onEvent('sources', sources);
    const units = content.match(/[\s\S]{1,24}/g) || [];
    for (const text of units) {if (signal.aborted) break; message.content += text; onEvent('token', {text}); await new Promise(resolve => setTimeout(resolve, 8));}
    message.status = signal.aborted ? 'cancelled' : 'complete'; chat.updatedAt = now();
    const log = addLog('chat', question, message.content, state.kbs.filter((k: Row) => body.kbIds.includes(k.id)).map((k: Row) => k.name).join('、'), [], {id: requestId, traceId: requestId});
    log.status = signal.aborted ? 'cancelled' : 'success'; persist();
    if (!signal.aborted) onEvent('done', {session: clone(chat), message: clone(message), log: clone(log), simulation: true});
  }
  return {request, streamChat, snapshot: () => clean(clone(state))};
}

let adapter: ReturnType<typeof createPrototypeAdapter> | undefined;
function currentAdapter() {
  if (!adapter) {let storage: StorageLike | undefined; try {storage = globalThis.localStorage;} catch { /* Session-only prototype if storage is blocked. */ } adapter = createPrototypeAdapter(baseline, storage);}
  return adapter;
}
export function prototypeApi<T = any>(path: string, options: RequestInit = {}): Promise<T> {return currentAdapter().request<T>(path, options);}
export function prototypeStreamChat(body: any, onEvent: (event: string, data: any) => void, signal: AbortSignal): Promise<void> {return currentAdapter().streamChat(body, onEvent, signal);}
