# 观测中心 · 真实 traceId（MVP）

> 落地时间：2026-10-29（Asia/Shanghai）  
> 范围：enterprise-kb 仓库；投影现有实体，不新建 obs 表 / 不计费账单 / 不实现 Agent Harness。

## 1. 映射约定

| 域 | 根实体 | `traceId` | 响应里还能看到 |
|----|--------|-----------|----------------|
| 对话 chat | `log` | `log.id`（形如 `req-…`） | SSE `meta.traceId`、`X-Request-ID`、`requestId` |
| 检索 retrieval | `log` | 同上 | `POST …/retrieve` 返回 `traceId` |
| 知识构建 import | `task` | `task.id`（=`task.traceId`） | import `log.id` / `log.traceId` 与 task 相同 |
| 应用运行 | `application_run` | `run.id`（=`runId`=`traceId`） | `POST …/run` 响应 |

原则：

- **一个用户触发的端到端动作 = 一个 traceId**，等于根实体主键，避免双写难查。
- 持久化记录一律带显式字段 `traceId`（与 id 相等），便于列表过滤与互链。
- **不伪造 token**：供应商未返回则为 `null` / 「未知」；计费 Tab 无单价时金额为 `—`。

## 2. 只读 API

前缀：`/api/observability`（需 manager/admin）

```http
GET /api/observability/overview
GET /api/observability/traces?rootType=&status=&q=&limit=&offset=
GET /api/observability/traces/{traceId}
GET /api/observability/billing
```

`GET …/traces/{traceId}` 聚合：

| 字段 | 说明 |
|------|------|
| `trace` | 摘要（rootType / status / tokens / duration / attrs） |
| `steps` | log.steps 或 application_run.steps → span 列表；无则 `[]` |
| `buildStages` | 仅 import：upload_received→parse→chunk→metadata_extract→index→publish；无计时则为 `duration: null`，状态可为 `unknown` |
| `toolCalls` / `skillCalls` / `harnessErrors` | 恒为 `[]`（缺口），`gaps` 文案标明 |
| `input` / `output` / `error` / `sources` | 有则填，无则 null / `[]` |

不存在的 trace → **404**。缺域不编造数据。

## 3. 构建流水线投影

来源优先级：`import log.steps` 计时与状态 + `task` 的 stage/status/options。

| 标准阶段 | 现状来源 |
|----------|----------|
| upload_received | task 创建即成功；attrs 带 parser/chunkStrategy 等 options |
| parse | step「文档解析与图像理解」 |
| chunk | 无独立 step 时：parse 成功则标 success，`duration: null`，attrs.note 说明合并在解析 |
| metadata_extract | step「元数据抽取」；未开抽取则可能仍为 unknown |
| index | step「向量索引」 |
| publish | task/log success → success；task=review → pending |

失败时把 `task.error` 挂在推断阶段，**不编造耗时**。

## 4. 前端

- 页：`frontend/src/pages/Observability.tsx`
- 去掉纯 mock 列表；空态用 Ant Empty
- 支持按 traceId 搜索并打开抽屉
- 对话 Tab 仍复用 `LogsPage`；log.id 即 traceId
- Agent Tab 以 application_run 为主，工具/Skill/Harness 列标「缺口」
- 计费 Tab：`/billing` 聚合已知 token，金额 `—`

原型模式：`frontend/src/prototype/api.ts` 提供同路径 stub。

## 5. 手动验收

```bash
# 后端
cd backend && .venv/bin/pytest tests/test_observability.py -q
# 全量（尽量绿）
.venv/bin/pytest -q

# 前端类型
cd ../frontend && npx tsc -b

# 手工
# 1) 登录 manager/admin → 观测中心
# 2) 上传文档 → 构建 Tab 出现 traceId=taskId → 打开抽屉看 buildStages
# 3) 对话/检索 → 日志 id 可搜到同一 trace
# 4) 应用 run → Agent Tab 出现，gaps 含工具/Skill/Harness
# 5) 计费 Tab 无假金额
```

## 6. 非目标（本刀不做）

- 独立 `obs_spans` 表 / OTLP 导出
- 模型单价与人民币账单
- 真实 Tool / Skill / Harness 运行时
- 用户角色看观测中心（入口仍在管理区）
