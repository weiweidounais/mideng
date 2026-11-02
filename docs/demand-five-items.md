# 五项需求对照分析（密灯 / enterprise-kb）

> 日期：2026-10-29（Asia/Shanghai）  
> 范围：只读对照仓库代码 + 本轮有限写入（设计文档与原型观测页）  
> 原则：结论来自仓库事实；查不到标「待验证」，不编造生产行为。

---

## 本轮拟改 / 已改路径清单

| 路径 | 动作 | 说明 |
|------|------|------|
| `docs/demand-five-items.md` | 新建 | 本文件：需求 1–3 对照 + 总览 |
| `docs/prototype-implementation-gap.md` | 新建 | 需求 4：原型→实现缺口全表 |
| `docs/observability-design.md` | 新建 | 需求 5：可观测模块功能设计 |
| `frontend/src/types.ts` | 修改 | `View` 增加 `observability` |
| `frontend/src/store.tsx` | 修改 | hash 白名单增加 `observability` |
| `frontend/src/App.tsx` | 修改 | 导航「观测中心」、懒加载与路由渲染 |
| `frontend/src/pages/Observability.tsx` | 新建 | 观测中心原型页（mock 分区与字段表） |

**本轮已做**：父子切块 + 语义 LLM 切块（`recursive` / `parent_child` / `semantic`；语义失败降级 recursive）。**仍不做**：观测 API 改造、Agent Harness 埋点、计费账本等。（元数据 MVP 另见 import-metadata-extraction.md）

---

## 1）问答应用扩展：报告撰写 / 内容生成 / 审核

### 对照对象

- 前端原型：`frontend/src/pages/Applications.tsx`（`templateInfo` + `buildTemplate`）
- 后端：`backend/app/applications.py`、`backend/applications-contract.md`
- 节点种类双方一致：`start | knowledge | llm | condition | template | output`

### 已有场景模板（前端）

| 模板 kind | 名称 | 图结构 | 后端能力匹配 |
|-----------|------|--------|--------------|
| `knowledge` | 知识问答 | start → knowledge → llm（`requireEvidence: true`）→ output | **已有**：节点与执行引擎支持；`requireEvidence` 合同已写明 |
| `rewrite` | 文案改写 | start → llm → output | **已有**：不依赖知识库；`requireEvidence` 默认 false |
| `routing` | 规则分流 | start → condition → template×2 → output | **已有**：条件 true/false 分支；无模型也可跑 |

### 需求场景对照

| 业务场景 | 现状判定 | 说明 |
|----------|----------|------|
| 内容生成（摘要/邮件/业务文案） | **本轮已做（MVP）** | 新增 `generate` 多段/风格模板；另保留「文案改写」。批量/入库/导出仍缺口 |
| 报告撰写 | **本轮已做（MVP）** | 已有 `report` 模板（大纲→检索→成稿→引用约束）；多轮章节/导出仍缺口 |
| 审核场景 | **本轮已做（MVP）** | 新增 `review` 模板（检索+清单/风险+人工确认栏说明）；人审状态机/确认 API 仍缺口 |
| 应用运行观测 | **部分** | 运行返回 `steps/tokens/duration/sources`；与「日志与监测」未统一为 Agent 级观测（见观测设计） |

### 改造点（设计级，本轮不实现后端）

1. **模板扩展**：在 `templateInfo` / `buildTemplate` 增加 `report`（报告撰写）、`review`（审核）模板；后端无需新 kind 即可先用现有节点演示，后续再加 `human` / `export` 节点。
2. **报告模板建议图**：start → knowledge → llm（章节提纲）→ llm（正文）→ template（引用附录）→ output；`requireEvidence` 对事实段开启。
3. **审核模板建议图**：start → knowledge → llm（合规要点）→ condition（关键词/风险）→ template（通过/驳回文案）→ output；真正「人审」需新节点与 API（缺口）。
4. **合同**：`applications-contract.md` 当前无 report/review 场景说明；落地前补场景约定与变量约定。

---

## 2）切块：父子切分 + LLM 语义切分

> **实现状态（2026-10-30）**：`parent_child` 与 `semantic`（LLM 语义切分，可降级）均已落地；默认 `recursive` 保持兼容。语义说明见 `docs/semantic-llm-chunking.md`。

### 现状（代码）

| 能力 | 位置 | 事实 |
|------|------|------|
| 切分算法 | `parsers.py` `_split` | `RecursiveCharacterTextSplitter`，`chunk_size`∈[200,1500]，overlap=`min(80, size//8)`，分隔符 `\\n\\n / \\n / 。 / ； / . / 空格` |
| 结构保留 | `parsers.py` | Markdown 标题树、Word Heading、PDF 页、表格整块、DocMind layout；**非**父子双层索引 |
| 上传参数 | `ingestion.py` `upload_documents` | `parser`=`auto|cloud`，`chunkSize`，`imageUnderstanding`，`autoPublish` |
| 导入 UI | `Knowledge.tsx` ImportModal | Slider「建议片段长度」+ 解析策略；文案写「优先保留标题…完整语义」，实为字符切分，**无**父子/LLM 语义选项 |
| 向量层 | `ingestion` 发布路径 | 按 chunk 列表建索引；chunk 结构无 `parentId` / `childOf` 字段约定 |

### 判定

| 需求项 | 判定 |
|--------|------|
| 父子切分（父段检索上下文 + 子段精细召回） | **本轮已做**（`chunkStrategy=parent_child`；默认仍 `recursive`） |
| LLM 语义切分（按主题边界切） | **本轮已做（MVP）**（`chunkStrategy=semantic`；无 LLM 降级；与检索 mode=`semantic` 无关） |
| 结构感知字符切分 + 云版面 | **已有** |

### 改造点（接口 / 字段 / UI）

**上传 Form / options（建议）**

```text
chunkStrategy: 'recursive' | 'parent_child' | 'llm_semantic'   # 默认 recursive
chunkSize: int                                                 # 子块或叶子块建议长度
parentChunkSize?: int                                          # 仅 parent_child
semanticModelConfigId?: string                                 # 仅 llm_semantic
```

**Chunk 字段（建议）**

```text
id, title, content, location, kind
parentId?: string
role?: 'parent' | 'child' | 'leaf'
semanticBoundary?: string   # LLM 切分理由，可审计
```

**检索**：子块命中后回填父块正文进 `context`（改 `rag.py` 组装逻辑）。  
**UI**：导入第 2 步增加切分策略单选；预览区分父/子；费用提示（LLM 切分会耗 token）。  
**观测**：构建任务记录 `chunkStrategy`、块数、切分耗时与 token（见观测设计）。

---

## 3）导入后自动抽元数据并索引

### 现状

| 已有元信息 | 来源 | 是否「自动业务元数据」 |
|------------|------|------------------------|
| 文档名、格式、大小、sha256、版本、状态 | `ingestion.py` | 文件级技术字段，**已有** |
| chunk `title` / `location` / `pages` / `parser` / `sheet` 等 | `parsers.py` | 结构位置元数据，**已有** |
| 知识库 `tags` / `category` | 建库表单 | 人工填写，**部分** |
| 时间、版本号（业务文档版本）、主体、负责人、关键词、可能被问到的问题 | — | **缺口**：解析与发布链路无 LLM/规则抽取步骤，未写入可检索 payload |

Qdrant / 检索侧：`rag.py` 主要用 chunk 正文 + 文档名做向量/关键词；未见独立「元数据字段过滤索引」产品面（业务标签过滤 **待验证** 是否在 payload 过滤里扩展——当前检索 API 以 query/topK/mode/rerank 为主）。

### 改造点

1. **流水线阶段**：parse → **extract_metadata** →（可选人工确认）→ index。  
2. **文档级字段建议**：`docDate`, `docVersion`, `subject`, `owner`, `keywords[]`, `suggestedQuestions[]`, `extractedAt`, `extractorModelId`。  
3. **索引**：关键词可进 BM25 语料；`suggestedQuestions` 可作伪查询增强或单独 FAQ 集合；过滤字段进 vector payload。  
4. **UI**：任务详情展示抽取结果；发布前可改；知识库列表/检索测试可按主体/负责人筛选。  
5. **计费**：抽取调用记入构建过程用量（观测「知识库构建」+「计费」）。

---

## 补充材料

`docs/002_*.md` 为同日并行盘点/设计长稿（切块元数据、缺口细表、可观测）；本文件与 `prototype-implementation-gap.md` / `observability-design.md` 为本任务主交付入口。

## 四点与五点索引

- **完整缺口表** → [`prototype-implementation-gap.md`](./prototype-implementation-gap.md)
- **可观测设计 + 原型入口说明** → [`observability-design.md`](./observability-design.md)

---

## 简要结论

1. 应用侧：问答/改写/分流 **已有**；报告撰写、审核 **缺口**；内容生成靠改写模板 **部分**。  
2. 切块：结构+递归字符切分 **已有**；父子切分 **本轮已做**；LLM 语义切分 **缺口**。  
3. 元数据：技术/位置字段 **已有**；业务元数据自动抽取与索引 **缺口**。  
4. 缺口清单与观测原型见上述两篇文档；本轮仅补观测中心 UI 草图，不改后端业务逻辑。
