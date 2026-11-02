# 切块预览与分块关键词增强（密灯 MVP）

> 日期：2026-10-30（Asia/Shanghai）  
> 更新：导入向导支持块级/文档级元数据标注；`chunk-preview` 返回 metadata；新增 enhance / batch 端点

## 做了什么

1. **分块关键词增强（无 LLM）**
   - `metadata_extract.enhance_chunks_with_keywords`：jieba/规则写入 `chunk.metadata.keywords`，并补 `subject` / `likelyQuestions`
   - 参数：`force`（覆盖未手改字段）、`skip_edited`（跳过 `metadata.edited=true` 的块）
   - `parse_file` 末尾默认调用；失败只写 warning，不阻断入库
   - 索引：`chunkKeywords` 进 Qdrant payload；BM25 语料拼接 chunk 关键词

2. **切块预览 API**
   - `POST /api/chunk-preview`（manager）
   - Form：`files`（≤1）或 `text` + `fileName`，以及 `chunkSize` / `chunkStrategy`（`recursive`|`parent_child`|`semantic`）/ `parentSize` / `chunkOverlap` / `enhanceKeywords` / **`extractMetadata`** / **`extractMetadataMode`**
   - 当 `extractMetadata=true`：同步返回文档级 `metadata`（`extract_document_metadata`），并把块级关键词增强写进各 `chunk.metadata`
   - 元数据失败只进 `warnings`，HTTP 仍 200，不 422
   - semantic：无模型时降级 recursive + warning；**不**因选 semantic 直接 422
   - 不落库；返回 `chunks` / `warnings` / `options` / `chunkCount` / `metadata?`

3. **块级再增强（不重解析）**
   - `POST /api/chunk-preview/enhance`（JSON）
   - Body：`{ fileName?, chunks, force?, skipEdited? }`
   - 对已有切块数组再跑 `enhance_chunks_with_keywords`；`edited` 块默认跳过

4. **批量文档元数据预览**
   - `POST /api/metadata-preview/batch`（manager，multipart `files` + `mode`）
   - 返回每文件 `{ name, metadata, warnings }`，不落库

5. **导入向导 UI（步骤「预览与确认」）**
   - Tab：**切块** | **文档元数据**
   - 切块 Tab：每块可编辑 keywords / subject / likelyQuestions；标签「自动」/「已修订」
   - 文档元数据 Tab：docDate / bizVersion / subject / ownerPerson / keywords / likelyQuestions
   - 按钮：当前文件自动抽取、批量自动抽取（所有文件）、重新增强块关键词
   - 提交导入时带上 `draftMetadataByFile`、`draftChunkMetaByFile`（JSON）；后端草稿优先，自动抽取只填空，不覆盖手改

6. **入库合并**
   - `merge_document_metadata`：草稿非空字段覆盖；草稿显式清空也记 `edited`
   - `apply_chunk_metadata_drafts`：按 index 写入块 metadata，保留 `edited`

## 验收步骤

1. live 模式打开知识库 → 导入 md/txt → 步骤 2 选策略 → 步骤 3 见真实片段 + 文档元数据 Tab
2. 手改某块关键词 → 点「重新增强」→ 该块应保留手改（「已修订」）
3. 提交导入后打开文档：文档元数据与块 metadata 与预览一致
4. semantic 未配模型：有切块 + warning，HTTP 200
5. `cd backend && uv run pytest -q tests/test_chunk_preview_and_enhance.py tests/test_import_metadata_preview.py`

## 语料

- 自造：`docs/testdata-mideng/`
- Mac AI客服整理：`qa/fixtures/mideng/`
