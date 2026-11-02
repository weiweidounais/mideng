# 父子切块实现说明

> 日期：2026-10-29（Asia/Shanghai）  
> 范围：仅 `parent_child` 可配置切块；不做 LLM 语义切分、不做元数据抽取、不改观测 API。

## 行为

| 项 | 说明 |
|----|------|
| 策略 | `chunkStrategy=recursive`（默认，兼容旧库）或 `parent_child` |
| 参数 | `chunkSize`（子块/叶子）、`parentSize`（仅父子）、`chunkOverlap`（可选，默认 `min(80, size//8)`） |
| 结构 | parent 大块 + child 小块；child 带 `parentId`、`parentExcerpt`、`role`、`splitter` |
| 索引 | parent **不进** Qdrant；child/无 role 块进向量；payload 可含 `parentId`/`role`/`parentExcerpt` |
| 检索 | 候选排除 parent；`_source` 命中 child 时拼 `parentContext` 并扩写 `content` |

## 涉及文件

- `backend/app/parsers.py`
- `backend/app/ingestion.py`
- `backend/app/rag.py`
- `frontend/src/pages/Knowledge.tsx`、`frontend/src/types.ts`
- 测试：`backend/tests/test_parent_child_chunking.py`、`test_ingestion.py::test_upload_parent_child_strategy_persists_and_parses`
