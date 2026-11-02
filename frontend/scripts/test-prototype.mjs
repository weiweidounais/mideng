import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import ts from 'typescript';

// Execute the real TypeScript adapter with a tiny fixture, not a parallel mock.
const seed = {
  kbs: [{id: 'kb-fixture', name: '原型验收资料', embedding: 'fixture-space', description: '', tags: [], status: 'ready'}],
  docs: [{id: 'doc-fixture', kbId: 'kb-fixture', name: '已上传资料.md', kind: 'md', size: '1 KB', version: 1, status: 'ready', chunks: [{id: 'chunk-fixture', title: '采购流程', content: '采购需要提交预算审批。', location: '第 1 节', kind: 'text'}]}],
  tasks: [], models: [], connections: [], sessions: [], logs: [], settings: {}, applications: [], applicationRuns: [],
};
const originalSeed = JSON.stringify(seed);
const memory = new Map();
const storage = {getItem: key => memory.get(key) ?? null, setItem: (key, value) => memory.set(key, value)};
let networkCalls = 0;
const source = fs.readFileSync(new URL('../src/prototype/api.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true}}).outputText;
const module = {exports: {}};
vm.runInNewContext(js, {
  exports: module.exports, module,
  require: name => {assert.equal(name, './baseline.json'); return seed;},
  crypto: webcrypto, structuredClone, setTimeout, FormData, AbortController,
  fetch: () => {networkCalls++; throw new Error('Network must remain unreachable');},
});
const {createPrototypeAdapter, PROTOTYPE_STORAGE_KEY} = module.exports;
const adapter = createPrototypeAdapter(seed, storage);
const req = (path, method = 'GET', data) => adapter.request(path, {method, ...(data === undefined ? {} : {body: JSON.stringify(data)})});
let count = 0;
async function check(name, callback) {await callback(); count++; console.log(`✓ ${name}`);}

await check('原型初始化保留现有资料，仅补充明确标记的模拟模型', async () => {
  const state = await req('/state');
  assert.equal(state.docs[0].chunks[0].content, '采购需要提交预算审批。');
  assert.equal(state.models.filter(m => m.simulation && m.name.includes('模拟')).length, 5); // 4 capabilities plus bound embedding alias.
  assert.equal(state.runtime.prototype, true);
  assert.equal((await req('/session')).role, 'admin');
});
await check('模型字段保存、编辑与Key/口令不落盘', async () => {
  const result = await req('/models/configure', 'POST', {connectionMode: 'new', name: '自定义原型模型', provider: 'OpenRouter', type: 'LLM', api_key: 'key-must-never-persist', base_url: 'https://unused.invalid/v1', model: 'user/model'});
  assert.equal(result.model.modelId, 'user/model');
  assert.equal(result.connection.baseUrl, 'https://unused.invalid/v1');
  assert.equal(result.connection.keyConfigured, true);
  await req(`/models/${result.model.id}/configure`, 'PATCH', {connectionMode: 'existing', connectionId: result.connection.id, name: '改名', modelId: 'user/model'});
  await req('/auth/password', 'POST', {role: 'admin', oldPassword: 'old-should-not-persist', password: 'password-should-not-persist'});
  const saved = memory.get(PROTOTYPE_STORAGE_KEY);
  for (const secret of ['key-must-never-persist', 'old-should-not-persist', 'password-should-not-persist']) assert.ok(!saved.includes(secret));
  const tested = await req(`/models/${result.model.id}/test`, 'POST', {});
  assert.ok(tested.message.startsWith('本地原型模拟'));
  assert.equal(tested.usage, null);
});
await check('删除仅改变副本，固定baseline不被引用修改，重开可恢复原型草稿', async () => {
  await req('/knowledge-bases/kb-fixture', 'PATCH', {name: '原型中的改名'});
  const reopened = createPrototypeAdapter(seed, storage);
  assert.equal((await reopened.request('/state')).kbs[0].name, '原型中的改名');
  assert.equal(JSON.stringify(seed), originalSeed);
});
await check('文本读取与二进制占位明确区分，不持久化File', async () => {
  const form = new FormData(); form.append('files', new Blob(['# 原型导入\n这是真实选择的文本内容。']), 'test.md'); form.append('autoPublish', 'false');
  const upload = await adapter.request('/knowledge-bases/kb-fixture/documents', {method: 'POST', body: form});
  const doc = await req(`/documents/${upload.tasks[0].docId}`);
  assert.ok(doc.draftChunks[0].content.includes('真实选择的文本内容'));
  assert.equal(doc.status, 'review');
  await req(`/documents/${doc.id}/publish`, 'POST', {});
  assert.equal((await req(`/documents/${doc.id}`)).status, 'ready');
  const binary = new FormData(); binary.append('files', new Blob(['not-a-real-pdf']), 'test.pdf'); binary.append('autoPublish', 'false');
  const result = await adapter.request('/knowledge-bases/kb-fixture/documents', {method: 'POST', body: binary});
  const placeholder = await req(`/documents/${result.tasks[0].docId}`);
  assert.ok(placeholder.draftChunks[0].content.includes('未进行真实 OCR'));
  assert.ok(!memory.get(PROTOTYPE_STORAGE_KEY).includes('not-a-real-pdf'));
});
await check('检索与SSE包含明确模拟说明、来源与完成事件，不伪造tokens', async () => {
  const retrieval = await req('/knowledge-bases/kb-fixture/retrieve', 'POST', {query: '采购预算'});
  assert.ok(retrieval.results.length > 0);
  const events = [];
  await adapter.streamChat({kbIds: ['kb-fixture'], question: '采购流程'}, (event, data) => events.push({event, data}), new AbortController().signal);
  assert.equal(events[0].event, 'meta');
  assert.equal(events.at(-1).event, 'done');
  assert.ok(events.at(-1).data.message.content.startsWith('本地原型模拟'));
  assert.equal(events.at(-1).data.message.tokens, null);
  assert.ok(!JSON.stringify(events).includes('/api/'));
});
const graph = {
  name: '原型条件应用', description: '',
  nodes: [
    {id: 'start', kind: 'start', label: '开始', position: {x: 0, y: 0}, config: {}},
    {id: 'route', kind: 'condition', label: '条件', position: {x: 100, y: 0}, config: {source: '{{input}}', operator: 'contains', value: '采购'}},
    {id: 'yes', kind: 'template', label: '采购分支', position: {x: 200, y: 0}, config: {template: '采购指引：{{input}}'}},
    {id: 'no', kind: 'template', label: '其他分支', position: {x: 200, y: 100}, config: {template: '通用指引'}},
    {id: 'answer', kind: 'output', label: '输出', position: {x: 300, y: 0}, config: {template: '{{previous.output}}'}},
  ],
  edges: [
    {id: 'a', source: 'start', target: 'route'},
    {id: 'b', source: 'route', target: 'yes', sourceHandle: 'true'},
    {id: 'c', source: 'route', target: 'no', sourceHandle: 'false'},
    {id: 'd', source: 'yes', target: 'answer'}, {id: 'e', source: 'no', target: 'answer'},
  ],
};
await check('节点分流、发布快照与原型角色界面隔离', async () => {
  const app = await req('/applications', 'POST', graph);
  assert.equal((await req(`/applications/${app.id}/validate`, 'POST', {})).valid, true);
  await req(`/applications/${app.id}/publish`, 'POST', {});
  const first = await req(`/applications/${app.id}/run`, 'POST', {input: '采购电脑', mode: 'published'});
  assert.equal(first.output, '采购指引：采购电脑');
  assert.equal(first.steps.find(s => s.nodeId === 'no').status, 'skipped');
  assert.equal(first.tokens, null);
  const edited = structuredClone(graph); edited.nodes[2].config.template = '未发布内容';
  await req(`/applications/${app.id}`, 'PATCH', {...edited, expectedRevision: 1});
  await req('/auth/login', 'POST', {role: 'user', password: 'role-password-never-saved'});
  const metadata = await req(`/applications/${app.id}`); assert.equal(metadata.nodes, undefined);
  assert.equal((await req(`/applications/${app.id}/run`, 'POST', {input: '采购设备', mode: 'published'})).output, '采购指引：采购设备');
  await assert.rejects(req(`/applications/${app.id}/run`, 'POST', {input: '采购设备', mode: 'draft'}), error => error.status === 403);
  await req('/auth/login', 'POST', {role: 'admin'});
  const exported = await req('/configuration-export');
  assert.equal(exported.prototype, true); assert.ok(exported.applications.length);
  assert.ok(!JSON.stringify(exported).includes('role-password-never-saved'));
});
await check('未知路由失败关闭、模拟保存失败回滚、不触发fetch', async () => {
  const before = JSON.stringify(adapter.snapshot());
  await assert.rejects(req('/not-implemented', 'POST', {apiKey: 'never-store-this'}), error => error.status === 501);
  assert.equal(JSON.stringify(adapter.snapshot()), before);
  await assert.rejects(req('/models/configure', 'POST', {connectionMode: 'new', apiKey: 'never-store-this'}));
  assert.equal(JSON.stringify(adapter.snapshot()), before);
  assert.equal(networkCalls, 0);
  assert.equal(JSON.stringify(seed), originalSeed);
});
console.log(`${count} prototype adapter checks passed; no backend/network calls.`);
