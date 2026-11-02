# 评测门禁 · 不可变版本/回滚 · Trace→Case（密灯 MVP）

> 日期：2026-10-30（Asia/Shanghai）  
> 对齐知枢思路，落在密灯应用层与可观测层；不伪造 usage/token。

## 1. 应用草稿 / 已发布隔离 + 评测门禁

### 行为

- 草稿与 `published` 快照隔离（原有能力保留）
- `POST /api/applications/{id}/publish` 可选 body：
  - `requireEval`（默认 false）
  - `evalCases[]`：`{input, expectContains?, expectStatus}`（最多 20）
  - `minPassRate`（默认 1.0）
- `requireEval=true` 时：对**草稿**跑简化 pass/fail（`_execute(..., persist=False)`），不写 application_run；未达通过率 → **422** + `detail.evalReport`，拒绝发布
- 空 POST / `{}` 仍可直接发布（兼容旧客户端）
- 发布时把上一版 `published` 深拷贝进 `publishedVersions`（最多 20），新快照带 `immutable: true`

### UI

- 应用工作室 → **发布应用**：弹窗可开关「评测门禁」、编辑 Case JSON、看评测报告
- 通过后卡片/编辑器显示已发布版本号

## 2. 不可变版本 + 回滚

### API

- `GET /api/applications/{id}/versions` → `{current, history, publishedRevision, count}`
- `POST /api/applications/{id}/rollback` body `{revision}`  
  - 切换当前 `published` 指针；当前版归档进 history  
  - **绕过评测门禁**；草稿不变；`hasUnpublishedChanges=true`；`lastRollback.bypassedEvalGate=true`

### UI

- 编辑器工具栏 **版本** → 抽屉列当前/历史 → **回滚到此版本**

## 3. Trace→Case 回流

### API

- `POST /api/observability/traces/{traceId}/to-case`  
  body：`{label: good|bad, kbId?, query?, answer?, expectedDocIds?, note?}`  
  - 从 chat log / application_run 提取 query/answer/sources  
  - 成功：`{ok:true, case}`（含 `importable` 供 RagWorkbench 结构导入）  
  - 失败软返回：`{ok:false, error}`（**HTTP 200**，不阻断主流程）
- `GET /api/observability/eval-cases?kbId=&label=&limit=`

### UI

- 可观测 → 打开 Trace 抽屉 → **标为 Good Case / Bad Case**

## 验收步骤

1. 创建模板应用 → 发布（无门禁）→ 改草稿再发布 → 版本抽屉可见历史 → 回滚到上一版 → 运行输出为旧版文案
2. 发布时开评测门禁，Case 要求不存在的 `expectContains` → 422，应用仍为草稿
3. 对话或应用运行产生 trace → 可观测详情 → Good/Bad → `GET /eval-cases` 可见
4. `cd backend && uv run pytest -q tests/test_eval_gate_versions_rollback.py tests/test_observability.py`

## 已知限制

- 门禁 Case 为简化 contains/status，未接完整 RAGAS / RagWorkbench 批跑 UI
- 回滚只切换已发布快照，不自动覆盖草稿节点
- Trace→Case 不自动写入 RagWorkbench 评测集实体，提供 `importable` 结构由人工/后续导入
- 评测执行不伪造 tokens；无模型节点的模板应用 tokens 仍为 null
