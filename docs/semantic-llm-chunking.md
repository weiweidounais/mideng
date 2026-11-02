# 语义 LLM 切块实现说明

> 日期：2026-10-30（Asia/Shanghai）  
> 范围：仅 `semantic`（别名 `llm_semantic` / `semantic_llm`）可配置切块；**本轮不与 `parent_child` 叠加**；不重做观测/元数据/场景模板。

## 行为

| 项 | 说明 |
|----|------|
| 策略 | `chunkStrategy=recursive`（默认）\| `parent_child` \| `semantic` |
| 参数 | `chunkSize`（建议段长）、`chunkOverlap`、可选 `semanticModelConfigId`、`maxSemanticCallsPerDoc`（默认 40） |
| LLM | 有已配置且可用的 LLM 时，提示词约束输出 JSON：`{"paragraphs":[{"text","reason"}]}`；sanitize 空段/过长段；超长原文尾部递归补切 |
| 降级 | 无 LLM / 初始化失败 / JSON 非法 / 调用上限 → **递归字符切分**；`warnings` 写明原因；**不阻断入库** |
| usage | 仅合并供应商返回的 token；缺失则记未知（不写入伪造数字） |
| Chunk 标记 | 成功：`splitter=semantic`，可选 `semanticBoundary`；降级：`splitter=recursive` + `semanticFallback=true` |

## 涉及文件

- `backend/app/parsers.py`（`normalize_chunk_options` / `_split_semantic` / `parse_file`）
- `backend/app/ingestion.py`（Form 校验与 task options）
- `frontend/src/pages/Knowledge.tsx`（导入「语义切分」选项与费用提示）
- 测试：`backend/tests/test_semantic_chunking.py`、`test_ingestion.py::test_upload_semantic_strategy_persists_and_degrades_without_llm`

## 手动验收

1. 未配置 LLM：导入选「语义切分」→ 任务成功入库，文档 `warnings` 含降级说明，片段为递归结果。  
2. 已配置可用 LLM：同步骤 → 片段带 `splitter=semantic`；任务 usage 仅在有供应商回传时出现 `llmTokens`。  
3. 选「父子切分」与「语义切分」互斥（UI 单选）；本轮不组合。
