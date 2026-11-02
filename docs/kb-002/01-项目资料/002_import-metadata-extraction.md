# 导入元数据抽取（需求 3 · MVP）

导入/解析流水线在切块之后增加「文档级 + 块级元数据」步骤，结果写入 `doc.metadata` 与 `chunk.metadata`，并进入检索路径。

## 固定字段（文档级 `doc.metadata`）

| 字段 | 含义 | 说明 |
|------|------|------|
| `docDate` | 时间 | 文档相关日期（生效/修订/发布等），`YYYY-MM-DD` |
| `bizVersion` | 版本 | 业务版本号（如 `V2.1` / `Rev A`），与发布次数 `doc.version` 分开 |
| `subject` | 主体信息 | 适用组织 / 产品 / 业务主体 |
| `ownerPerson` | 负责人 | 编制 / 责任人等 |
| `keywords` | 检索关键词 | 字符串数组，参与过滤与词法检索 |
| `likelyQuestions` | 可能被问到的问题 | 字符串数组，参与词法检索（BM25 旁路） |
| `extractedAt` | 抽取时间 | ISO UTC |
| `extractor` | 抽取器信息 | `{ mode, modelConfigId?, edited?, llmAttempted? }` |
| `confidence` | 置信度 | 0–1 或 null |
| `status` | 状态 | `ok` / `partial` / `empty` / `failed` / `skipped` |

## 块级字段（`chunk.metadata`）

| 字段 | 含义 |
|------|------|
| `keywords` | 本块关键词 |
| `subject` | 本块主题/标题摘要 |
| `likelyQuestions` | 本块可能被问到的问题 |
| `source` | `auto` / `manual` 等 |
| `extractor` | 如 `rules` |
| `edited` | 人工修订标记；为 true 时自动增强默认跳过 |

## 流程

1. 解析与切块完成后，若任务选项 `extractMetadata=true`（默认）且 `extractMetadataMode≠off`，执行文档级抽取。
2. **启发式优先**（`rules`）：YAML frontmatter、标题、正文正则、文件名、jieba、模板问题。
3. **可选 LLM**（`llm` / `auto` 且传入 `db`）：仅已配置可用 LLM 时调用；失败保留启发式并记 warning，**从不伪造供应商 usage**。
4. 块级：`enhance_chunks_with_keywords` 写 keywords/subject/likelyQuestions。
5. **导入草稿优先**：若 Form 带 `draftMetadataByFile` / `draftChunkMetaByFile`，`merge_document_metadata` / `apply_chunk_metadata_drafts` 先合入手工值，再对空字段填自动结果；手改字段不覆盖。
6. 结果写入 `doc.metadata` 与块 metadata；失败不阻断入库。
7. 索引：短字段进 Qdrant payload；keywords + likelyQuestions 进 BM25。
8. 检索：`keywordsAny` 过滤；`publish` / `reindex` 已有可用元数据则跳过重抽。

## 导入 Form 字段

| 字段 | 说明 |
|------|------|
| `extractMetadata` | bool，默认 true |
| `extractMetadataMode` | `off\|rules\|llm\|auto`，默认 `auto` |
| `draftMetadataByFile` | JSON：`{ "文件名": { docDate, bizVersion, subject, ownerPerson, keywords, likelyQuestions } }` |
| `draftChunkMetaByFile` | JSON：`{ "文件名": [ { index, metadata } ] }` |

## API

- `PATCH /api/documents/{id}/metadata` — 人工修订（标记 `extractor.edited`）
- `POST /api/documents/{id}/metadata/extract` — 手动重抽
- `POST /api/chunk-preview` — 切块预览；`extractMetadata=true` 时附带文档/块元数据
- `POST /api/chunk-preview/enhance` — 对已有切块再增强关键词（跳过 edited）
- `POST /api/metadata-preview/batch` — 多文件文档元数据预览（不落库）

## 前端（导入向导）

- 步骤「预览与确认」：Tab **切块** | **文档元数据**
- 块级可编辑 keywords / subject / likelyQuestions；标签「自动」「已修订」
- 「当前文件自动抽取」「批量自动抽取」「重新增强块关键词」
- 提交时草稿随导入 Form 提交，后端不覆盖手改

## 如何验收

1. 含 frontmatter 的 Markdown 导入，文档预览「元数据」页签可见六类字段，`status=ok`。
2. 导入向导手改块关键词后提交，入库后该块仍为手改值且 `edited=true`。
3. 关闭「自动抽取元数据」再导入，无可用抽取或 `skipped`。
4. 检索工作台关键词 tag 可过滤。
5. 无 LLM 时 extractor `mode=rules`，不伪造 tokens。

## 测试

```bash
cd backend && pytest tests/test_metadata_extract.py tests/test_ingestion.py tests/test_import_metadata_preview.py -q
cd backend && pytest -q
```

详见 `docs/chunk-preview-and-enhance.md`。
