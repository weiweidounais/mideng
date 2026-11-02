# RAG 中台可观测模块功能设计

> 产品：知序（enterprise-kb）  
> 状态：设计稿（本轮不实现后端埋点与生产链路）  
> 原型页：`frontend/src/pages/Observability.tsx`，路由 hash `#/observability`，导航名「观测中心」

---

## 1. 目标与范围

统一展示四类过程信号，支撑排障、合规审计与成本控制：

| 观测域 | 覆盖内容 |
|--------|----------|
| 知识库构建 | 上传→解析→切块→（元数据抽取）→索引→发布；失败与重试 |
| Agent 调用 | 应用工作流 / 未来 Agent Harness：输入输出、状态、工具与 Skill、token、上下文、异常 |
| 对话日志 | 问答会话、检索步骤、引用、反馈 |
| 计费消耗 | 按模型/供应商/场景/库汇总 token 与预估费用 |

与现有「运维 → 日志与监测」关系：日志页保留为原始请求流；观测中心做**分域看板 + 结构化字段表 + 关联下钻**。短期可同读 `log` 实体 + 任务/应用 run 数据；长期独立观测索引。

---

## 2. 信息架构（原型）

```
观测中心
├── 总览（今日请求、失败率、token、构建任务、告警条）
├── 知识库构建
├── Agent 调用
├── 对话日志
└── 计费消耗
```

导航：主导航增加「观测中心」（`view=observability`）。原型与 live 均可进入；live 数据未接时页面用 mock 并提示「设计稿 / 假数据」。

---

## 3. 知识库构建过程

### 3.1 流水线阶段（建议事件）

`upload_received` → `parse_started/finished` → `chunk_started/finished` → `metadata_extract_*`（规划）→ `index_started/finished` → `publish_done` | `failed`

### 3.2 关键字段

| 字段 | 说明 |
|------|------|
| taskId / libraryId / documentId | 关联 |
| stage / status | 阶段与成功失败取消 |
| parser / chunkStrategy / chunkSize | 构建参数 |
| chunkCount / parentCount | 产出规模 |
| durationMs / errorCode / errorMessage | 耗时与错误 |
| tokensPrompt/Completion | 云解析、图意、未来语义切分/抽元数据 |
| provider / modelConfigId | 所用模型 |

### 3.3 原型交互

任务列表 + 时间线；点开看阶段条与错误；链到知识库文档。

---

## 4. Agent 调用过程（需求字段对齐）

> 当前应用 `run` 返回 steps/tokens；无独立 Agent/Skill/Harness。下表为**目标模型**，原型用 mock 演示。

| 需求字段 | 设计落点 | 现状 |
|----------|----------|------|
| 单次输入 | `input.prompt` / 变量快照（脱敏） | 部分（应用 input） |
| 单次输出 | `output.text` / 结构化结果 | 部分 |
| 运行状态 | `queued|running|succeeded|failed|cancelled` | 部分（同步 run） |
| 工具调用状态 | `toolCalls[]`: name, argsHash, status, latency, error | 缺口 |
| Skill 调用 | `skillCalls[]`: skillId, version, status, tokens | 缺口 |
| 单次 token | prompt/completion/total；以供应商为准 | 部分（日志） |
| 调用上下文 | userId, appId, sessionId, libraryIds, traceId | 部分 |
| Harness 异常 | `harnessErrors[]`: type, nodeId, stack摘要, recovered | 缺口 |

### 追踪模型建议

- `traceId`：一次用户触发端到端  
- `spanId`：节点/工具/Skill  
- 与现有 `log.id`、应用 `runId` 可互链

---

## 5. 对话日志

复用并增强现有 chat/retrieval 日志：

- 列表：时间、用户、会话、模式、命中数、token、耗时、反馈  
- 详情：检索 hits、prompt 摘要（权限控制）、回答、sources  
- 与 Agent 域：若问答升级为 Agent，同一 `traceId` 可跳转

隐私：非 admin 不可看他人全文；原型 mock 用占位。

---

## 6. 计费消耗

| 维度 | 指标 |
|------|------|
| 时间 | 日/周/月 |
| 模型 / 供应商 | token、调用次数、预估金额 |
| 场景 | chat / retrieval / import / application / metadata_extract / semantic_chunk |
| 知识库 | 构建+问答归因 |

依赖：模型单价配置（运维扩展）；无单价时只展示 token。预算阈值与告警为后续项。

---

## 7. API 草图（本轮不实现）

```http
GET /api/observability/overview
GET /api/observability/builds?libraryId=&status=
GET /api/observability/agent-runs?appId=&status=
GET /api/observability/agent-runs/{traceId}
GET /api/observability/conversations?...
GET /api/observability/billing?from=&to=&groupBy=
```

权限：`manager|admin` 读全量；`user` 仅本人对话与本人触发的构建。

落盘：短期投影现有 `log` + tasks + application_runs；中期 `obs_spans` 表或导出 OpenTelemetry。

---

## 8. 前端原型交付说明

| 项 | 路径 |
|----|------|
| 页面 | `frontend/src/pages/Observability.tsx` |
| 路由 | `types.ts` View + `store.tsx` hash + `App.tsx` nav/lazy |
| 样式 | 复用 `operations.css` 卡片/表格节奏；页内局部 class |
| 数据 | 页内 MOCK_* 常量；标明「原型假数据」 |

### 本地打开

```bash
cd /workspace/enterprise-kb/frontend
npm install          # 首次
npm run dev          # MODE=prototype，默认 http://127.0.0.1:5173
# 选择 manager/admin 角色 → 侧栏「管理与监测」→「观测中心」
# 或直接哈希：http://127.0.0.1:5173/#/observability
```

接真实后端时用 `npm run dev:live`（5174）并启动 API；观测 API 未落地前页面仍显示 mock，可与「日志与监测」对照。

---

## 补充材料

同目录并行盘点稿 `002_可观测模块设计_知枢.md` 含更细 OTel/Langfuse 参考与落库建议；**前端原型以本机 `Observability.tsx` 为准**。

## 9. 落地优先级（建议）

1. P0：总览 + 对话/日志投影到观测中心 UI（读现有 log）  
2. P1：构建任务时间线（读 tasks + import logs）  
3. P2：应用 run 结构化为 Agent 调用表（无工具/Skill 先空列）  
4. P3：计费单价与账单；Harness/Skill 随 Agent 运行时一并埋点  
5. 与切块/元数据需求同步：构建观测增加 `chunkStrategy`、抽取 token
