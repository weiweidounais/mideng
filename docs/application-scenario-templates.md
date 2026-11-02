# 应用场景模板（报告 / 内容生成 / 审核）

> 时间：2026-10-29（Asia/Shanghai）  
> 覆盖用户需求 1 的 MVP：在现有「应用生成」工作流上扩展内置模板，不另起产品。

## 结论

- 前端「从一个场景开始」现有 **6** 个内置模板：知识问答、文案改写、规则分流、**报告撰写**、**内容生成**、**制度审核**。
- 全部复用节点种类 `start | knowledge | llm | condition | template | output`，**未**新增脚本 / HTTP / 人审状态机节点。
- 创建时可写入可选字段 `scenario`（`report` / `generate` / `review` 等）；对话 Chat **无**场景来源字段，本轮不改 Chat。
- 调试 / 发布 / 运行仍走既有 `/applications/{id}/run`；响应继续带 `traceId`（= `runId`）。

## 模板图

| scenario | 名称 | 节点链 | 要点 |
|----------|------|--------|------|
| `report` | 报告撰写 | start → llm(大纲) → knowledge → llm(成稿, requireEvidence) → template → output | 成稿强制引用 `{{context}}`；缺依据即停 |
| `generate` | 内容生成 | start → llm → template → output | `requireEvidence=false`；提示词约定多段与风格 |
| `review` | 制度审核 | start → knowledge → llm(清单/风险) → output | 输出含人工确认栏文案；不自动裁决、无人审 API |

## 如何在 UI 创建并跑通

1. 以 **管理员 / 知识库管理人员** 登录，打开侧栏 **应用生成**。
2. 在「从一个场景开始」点选 **报告撰写 / 内容生成 / 制度审核**（或点「创建应用」后在弹窗切换类型）。
3. 填写名称 → **创建并编辑**。草稿会预填节点与提示词；`scenario` 随应用保存。
4. 在画布中检查：
   - 报告 / 审核：知识检索节点选好制度或资料库；两个模型节点选已验证 LLM。
   - 内容生成：只需对话模型。
5. **保存** → **校验** → **调试**：在运行面板输入题目、待审材料或多段生成说明，查看逐步输出与知识来源。
6. 通过后 **发布**；使用者可在应用中心运行已发布版本。观测中心可用返回的 `traceId` 打开运行轨迹。

## 代码位置

| 位置 | 作用 |
|------|------|
| `frontend/src/pages/Applications.tsx` | `templateInfo` / `buildTemplate` / 创建入口 |
| `frontend/src/pages/applications.css` | 新模板卡片配色与创建弹窗换行 |
| `backend/app/applications.py` | `Definition.scenario`；`scenario_template()`；发布快照带 scenario |
| `backend/tests/test_applications.py` | 结构校验 + 可创建 |

## 明确不做（本轮）

- 完整人工审批工作流 / SLA / 确认 API
- 报告多章循环改稿、导出 docx
- 内容生成批量条数、生成物自动入库
- 语义 LLM 切块、任意脚本 / HTTP 节点

## 与缺口清单

`docs/002_缺口清单_原型到实现.md` 中 **A5–A7** 已标为「本轮已做（MVP 模板）」；人审状态机、导出等仍属后续。
