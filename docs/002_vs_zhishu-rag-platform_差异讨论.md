# 002（本地 enterprise-kb）vs zhishu-rag-platform 差异讨论素材

> 用途：工作群讨论素材，**非终稿**（由 Grok Bot 汇总给用户）。  
> 盘点时间：2026-10-30（Asia/Shanghai）  
> A = 本地 `/workspace/enterprise-kb`（现产品展示名「**密灯 · 企业知识中台**」；历史文案曾称知序/知枢）  
> B = 公开仓 `https://github.com/chusimin/zhishu-rag-platform`（README 称「知枢 · AI 应用中台」；`private: false`，已用 GitHub 公开 API / raw 拉取）  
> 原则：**事实与观点分写**；路径写清楚；查不到标「待验证」。**未改业务代码。**

---

## 0. 对照范围与证据来源

| 侧 | 证据 |
|----|------|
| A | `README.md`、`compose.yaml`、`backend/pyproject.toml`、`frontend/package.json`、`backend/app/{rag,parsers,applications,observability,collaboration,security}.py`、`docs/002_*.md`、`docs/application-scenario-templates.md`、`integrations/README.md`、`backend/tests/` |
| B | 公开 API 仓元信息（更新约 2026-10-30 UTC）、`README.md`、`DESIGN.md`、`docs/AUDIT.md`（标注 2026-10-27，**部分结论已被后续提交超越，引用时需核对代码**）、`backend/pyproject.toml`、`docker-compose.yml`、`.env.example`、`backend/app/services/{chunking,retrieval,tools,metadata_extraction,chunk_enhancement}.py`、`backend/app/{tenancy,fde/*}.py`、`backend/app/api/routes/observability.py`、`backend/alembic/versions/*`、`prototype/` |

**访问说明**：本机 `gh` 未登录；公开 raw/API 可读，**不标「待验证」**。私有能力或线上真实部署效果未实测，相关处标「待验证」。

---

## 1. 定位 / 产品范围

### 事实

| 维度 | A（002 / enterprise-kb） | B（zhishu-rag-platform） |
|------|--------------------------|---------------------------|
| 自称定位 | 企业**知识中台**：知识入库 → 检索问答 → 应用节点编排；另有一期**协同工作台**（需求包 / 接口契约 / BOM / 例外） | **AI 应用交付中台**（面向 FDE / 解决方案）：模型接入 → 知识整理 → 搭应用 → **评测门禁发布** → 业务使用 → Trace 回流 Case |
| 知识库 | 有（多格式导入、任务中心、草稿检查/发布、版本） | 有（导入向导、按文件切块配置、分块增强、检索测试写回应用） |
| 应用编排 | 有：**节点画布**（`@xyflow/react`），六类节点 | 有：**简易应用 + Agent 类型**（Manifest）；README 写明 **Chat Flow「即将上线」**；`docs/AUDIT.md` 仍批评「单步 runtime」——与 README「Agent」并存，需以当前 `fde/runtime.py` 行为为准 |
| 协同 / 交付链 | **独有**：`backend/app/collaboration.py` + `frontend/src/pages/Collaboration.tsx` 等 | README / DESIGN **未见**需求—契约—BOM 协同模块 |
| 评测与发布治理 | RAG 工作台可做 Hit/Recall 等批量评测（`rag_workbench`）；**无**「评测集 = 发布门禁」产品闭环；NVIDIA RAGAS「尚未启用」（`integrations/README.md`） | **核心卖点**：评测集、AI 设计 Case、`is_release_gate`、不可变版本、回滚、线上 Trace 回流 Good/Bad Case（有迁移 `0007`/`0009` 与 `test_release_gate.py`） |
| 观测 / 运营 | 「观测中心」页 + `/api/observability/*`（从 log / application_run / task **投影**）；另有「日志与监测」 | 一级「可观测」：总览 / Trace / 会话 / 构建 / 费用（独立 `QueryLog` + traces，含 `cost`） |
| 业务端 | 使用者免登录可跑已发布应用；角色口令切换 | 工作台只见已发布应用；分享链接、API Token；管理端 / 业务端信息架构在 `DESIGN.md` 分写 |
| 工具平台 | 应用 **无** HTTP/脚本节点（README 刻意边界） | HTTP 业务工具 + 确认流（`services/tools.py`，迁移 `0003_tool_runtime`） |

### 观点（供讨论）

- A 更像「**企业内部知识 + 轻量编排 + 协同交付现场**」；B 更像「**对外交付 AI 应用的质量闭环平台**」。  
- 两边都叫/用过「知枢」，但产品重心不同；群讨论宜先统一「我们要对齐 B 的哪一层：知识 RAG、应用治理，还是整套 FDE」。

---

## 2. 技术栈

### 事实

| 层 | A | B |
|----|---|---|
| 前端 | React **19**、Vite 7、**Ant Design 5**、`@xyflow/react`、lucide；包名 `zhixu-knowledge-hub`；有 `prototype` / `live` 双模式 | React **18**、Vite 6、**无 Ant Design 依赖**（自研 `components/ui.tsx`）、React Router、Vitest；包名 `fde-ai-application-platform`；另有独立 `prototype/` 工作区 |
| 后端 | FastAPI、SQLAlchemy（同步为主）、Alembic、uv；包名 `zhixu-backend`；Python ≥3.12 | FastAPI、**SQLAlchemy Async**、Alembic、uv；包名 `fde-ai-platform-backend`；Python ≥3.11,<3.14 |
| 向量 / 检索存储 | **Qdrant**（本地 path 或 compose 服务）+ 业务库 SQLite/Postgres；BM25（`rank-bm25` + jieba）在进程内 | **PostgreSQL 16 + pgvector**（compose：`pgvector/pgvector:pg16`）；全文检索 + RRF 混合在 `services/retrieval.py`；**无 Qdrant 依赖** |
| 任务队列 | Celery + Redis（compose）；本地可 inline / 持久任务执行器 | Celery + Redis；本地可 `APP_TASK_MODE=inline` |
| 文件存储 | 本地 `DATA_DIR` / `.runtime` | 本地文件或 **S3 兼容**（compose 用 RustFS） |
| 模型接入 | 百炼 / OpenRouter / AIHubMix / DeepSeek 等；DocMind OCR；密钥服务端加密（`providers.py`） | OpenAI 兼容网关；OpenRouter / AIHubMix / DeepSeek / 通义手动；**测试替身**；OCR 默认 disabled（`.env.example`） |
| 部署 | 根 `Dockerfile` + `compose.yaml`：Postgres17 + Qdrant + Redis + api + worker；README：**本机未装 Docker，compose 未实机验证** | `backend/Dockerfile` + `docker-compose.yml`：Postgres(pgvector) + Redis + MinIO/RustFS + api + worker；前端 `pnpm dev` 另起 |

### 观点

- 向量底座差异大（Qdrant vs pgvector），**不能假设检索调参/运维经验直接搬运**。  
- A 前端组件库更重（Ant + 画布），B 更轻、更贴「交付控制台」视觉规范（`DESIGN.md`）。

---

## 3. RAG 能力

### 事实

| 能力 | A | B |
|------|---|---|
| 切块策略 | `parsers.py`：`recursive` / `parent_child` / `semantic`（LLM，失败降级）；导入可配 `chunkSize`/`chunkOverlap`/`parentSize`；文档见 `docs/parent-child-chunking.md`、`docs/semantic-llm-chunking.md` | `ChunkMethod` **九种**：recursive / heading / separator / fixed / parent_child / semantic / page / table_row / qa（`models.py` + `services/chunking.py`）；**按文件** `chunk_config`（迁移 `0004`） |
| 切块预览 | 有草稿片段修订 / 预览（知识页）；「按标题与语义结构」文案曾与实现不一致（缺口清单 B2，父子/语义本轮已补） | README：导入后真实切块预览、单文件调参 |
| 分块增强 | 文档级元数据抽关键词 / likelyQuestions（`metadata_extract.py`）；**非**逐 chunk 生成 QA 对写入向量的完整「enhance」流水 | `chunk_enhancement.py`：逐块关键词（可无模型规则）+ QA 对（需 LLM），拼进向量化文本 |
| 文档元数据 | MVP：`docDate` / `bizVersion` / `subject` / `ownerPerson` / `keywords` / `likelyQuestions` + `keywordsAny` 过滤（`docs/import-metadata-extraction.md`） | `metadata_extraction.py`：同类字段抽取 + 人工修订叙事（README） |
| 检索 | `rag.py`：`hybrid` / `semantic` / `keyword` + 可选 Rerank；父子检索可回填 `parentContext` | `retrieval.py`：`semantic` / `fulltext` / `hybrid`（RRF）+ 可选 Rerank；父子用 `parent_content` 回填展示 |
| 引用 | 来源含 chunk / version / 原件链接；Chat 来源抽屉 | README：回答附引用；Trace 含检索步骤 |
| 本地旁路引擎 | 有：`integrations` + knowledge-rag / FastEmbed / Chroma（与正式 Qdrant 双轨） | **未见**同等「本地旁路引擎」模块（待验证：是否计划中） |

**注意**：B 的 `docs/AUDIT.md`（2026-10-27）写「仅 3 种切块、缺混合检索」——与**当前** `ChunkMethod` 九值及 `retrieval.py` hybrid **不符**；讨论请以代码 / 新 README 为准，AUDIT 作历史差距记录。

### 观点

- B 切块「按格式自动匹配 + 九种方法 + 分块增强」产品化更完整；A 近期补齐父子/语义，但仍偏「三种策略 + 中文混合检索扎实」。  
- A 的 **jieba+BM25+Qdrant** 混合与 B 的 **pgvector+全文+RRF** 是两条工程路径；借鉴宜学「交互与配置粒度」，不宜整库换引擎除非有明确运维理由。

---

## 4. Agent / 应用

### 事实

| 项 | A | B |
|----|---|---|
| 应用模型 | 工作流图：`KINDS = start\|knowledge\|llm\|condition\|template\|output`（`applications.py`） | Manifest：`fde.app`；类型简易 / Agent；Chat Flow 未开放（README「当前边界」） |
| 场景模板 | 前端 6 套：知识问答、文案改写、规则分流、报告、内容生成、制度审核（`Applications.tsx` + `scenario_template()`） | 后端模板至少：知识库问答、通用内容创作、结构化报告、知识审校、智能客服（`fde/templates.py`，含 `human_handoff`） |
| 工具 | 无通用 HTTP/脚本节点 | HTTP 工具：Schema、鉴权、内网开关、副作用确认（`services/tools.py`） |
| Skill / Harness | 产品内**无**运行时；`.agents/skills/` 为开发态；观测页 Agent/Skill/Harness 多为空态或投影 gaps（`Observability.tsx` / `002_可观测*`） | 观测设计文档强调 Skill / Harness Span；**产品内完整 Agent ReAct + Skill 运行时成熟度待验证**（AUDIT 曾写无工具循环；其后有 `tool_runtime` 与 Agent 类型，需对照 `fde/runtime.py` 实测） |
| 流式 | Chat / 部分链路 **SSE** | README：**应用运行非流式**；旧问答 SSE 另线 |
| 版本 | 草稿 revision vs publishedRevision | 不可变 `AppVersion`、发布 / 下线 / 回滚、分享 `AppShare` |

### 观点

- A 已有**可视化多节点**（含条件分支），这是相对 B「Chat Flow 未上线」的短期优势。  
- B 的**发布门禁 + 版本/回滚 + 分享/API**是交付治理优势；A 若对标交付，应优先借治理闭环，而不是先借复杂 Agent 叙事。  
- 「Skill/Harness」两边文档热度都高于代码完备度，讨论时避免当成已交付能力。

---

## 5. 可观测与计费

### 事实

| 项 | A | B |
|----|---|---|
| 实现位置 | `backend/app/observability.py`（挂载于 `main.py`）；前端 `pages/Observability.tsx` | `api/routes/observability.py`；前端 `pages/ObservabilityPage.tsx` + `api/observability.ts` |
| Trace 模型 | MVP：**无独立 obs 表**；chat/retrieval→`log.id`；application→`application_run.id`；import→`task.id`（文件头注释） | 独立 `QueryLog` + 子 traces；`GET /runs/{trace_id}`；含 duration / tokens / **cost** |
| 计费 | `/observability/billing`：按来源聚合 **已知 tokens**，未知计数；**无价表/余额账本**（缺口清单 D10） | 模型可填单价；overview 汇总 `cost`；设计文档要求价格快照与账单同步状态（是否已全落地：**部分待验证**） |
| Agent 观测 | 明确 gaps：无 tool/skill/harness 调用列表时返回空 | 设计完整；代码是否写满 Skill/Harness span：**待验证**（至少有模型/检索/工具步骤叙事） |

### 观点

- 借 B：统一 Trace 对象、费用归因字段、会话与单次 Run 分离。  
- 不借：把「费用看板」先做成假精确账单；两边都应坚持「未知用量 ≠ 0」。

---

## 6. 部署与多租户 / 权限

### 事实

| 项 | A | B |
|----|---|---|
| 身份 | Cookie 会话；角色 `user` / `manager` / `admin`；管理口令 argon2（`security.py`）；使用者免登录但会话隔离 | 邮箱用户 + 密码；`Workspace` / `Membership.role`；`ApiClient` Token + scopes；审计事件（README） |
| 多租户 | **单实例口令模型**；未见 workspace 表 | `tenancy.py` ContextVar + `workspaces` 外键贯穿 |
| Compose 暴露 | DB/Qdrant/Redis **不**映射宿主机（更收紧） | Postgres/Redis/S3 **映射**高位端口（本地开发便利） |
| 生产清单 | README 备份 / SECRET_KEY / Cookie Secure 等 | README「生产检查清单」更完整（加密密钥、禁止 Demo Header、限流等） |

### 观点

- 若 002 只服务单一客户内网，A 模型够用；若要多客户交付，B 的 workspace + Token 更接近目标。  
- 权限模型迁移成本高，宜单独立项，勿与切块需求绑死。

---

## 7. 成熟度

### 事实

| 项 | A | B |
|----|---|---|
| 阶段自述 | README：「**本地原型调整**」；原型默认不碰真实后端；同时存在可联调真实 FastAPI | README 给完整「15 分钟上线」路径与生产清单；仍声明 Chat Flow / 部分渠道未开放 |
| 文档 | 近期 `docs/002_*`、缺口清单、观测设计很密；偏「盘点与增量」 | 对外 README + DESIGN + AUDIT + 评测回流文档 + 大量 `artifacts/` / `docs/images/` 截图 |
| 测试 | `backend/tests/` 十余个文件（含 parent_child / semantic / observability / applications）；前端以原型脚本为主 | 后端测试面更宽（评测门禁、tools 安全、fde、chunk_enhancement 等）；前端 Vitest（数量相对后端仍少，AUDIT 亦指出） |
| 原型双轨 | `frontend` 内 prototype/live 模式 | 根 `src/` 真前端 + `prototype/` 交互原型并存 |
| 未验证项 | A：compose 本机 Docker；云 OCR/模型费用实账。B：私有部署、Agent 深度、费用=账单一致性、渠道（企微/飞书） | 同左「待验证」 |

### 观点

- B 更「产品说明书完备」；A 更「现场联调 + 近期需求冲刺痕迹」。  
- 群讨论勿用截图数量代替能力验收；以可跑通路径 + 测试名为准。

---

## 8. 对 002 的可借鉴点 / 不应照搬点

### 可借鉴（观点，按性价比排序供拍板）

1. **发布门禁 + 评测集 + Trace 回流 Case**（B 差异化核心）→ 对齐「可上线、可回归」。  
2. **按文件的切块配置 + 导入预览 + 九种方法中的 heading/page/table_row/qa**（在 A 现有三种之上按需加，不必一次全搬）。  
3. **分块增强（关键词 / QA 对写入检索文本）** → 与 A 已有文档级 `likelyQuestions` 可合并设计，避免两套元数据。  
4. **不可变版本 / 回滚 / 分享链接 / API Token** → 补齐交付与集成面。  
5. **观测：会话 vs Trace 分层 + cost 字段（价表快照）** → 升级 A 当前「投影 MVP」。  
6. **HTTP 工具的安全默认值**（禁内网、副作用确认）→ 若 A 将来放开外部节点，直接抄安全策略，而不是先抄功能。

### 不应照搬（观点）

1. **换掉 Qdrant 整迁 pgvector**：无明确的多租户 SQL 一体化/运维诉求前，迁移成本 > 收益。  
2. **用 Manifest 单步运行时替换已有 xyflow 多节点**：A 已有条件分支与场景模板；更合理的是「治理层学 B，编排层留 A」，或等 B Chat Flow 真正落地再比。  
3. **把 DESIGN 里的 Skill/Harness 大词先做成空壳中心**：两边都容易文档超前；应先打通应用 run → 统一 Trace。  
4. **丢掉协同工作台**：B 没有对等模块；若 002 客户现场仍靠需求/契约/BOM，这是 A 护城河，不是「落后于 B」的删除项。  
5. **照搬 compose 端口全暴露或测试替身进生产**：学 B 的检查清单即可，默认安全姿态可继续比 B 本地 compose 更紧。  
6. **前端去 Ant 重写自研 UI**：无设计系统迁移预算时，只借信息架构与文案规范（`DESIGN.md`），不借换皮。

---

## 9. 一页对照（粘贴用）

| 维度 | A 002 | B zhishu |
|------|-------|----------|
| 定位 | 知识中台 + 节点应用 + **协同** | 应用交付中台 + **评测门禁** |
| 向量 | Qdrant | pgvector |
| 切块 | 3 策略（recursive/父子/语义） | 9 方法 + 分块增强 |
| 应用 | xyflow 多节点 | Manifest；Chat Flow 未上 |
| 观测计费 | 投影 MVP；tokens | QueryLog+cost；更完整 |
| 租户 | 角色口令 | Workspace+Token |
| 成熟度 | 原型/联调并行 | 文档与治理更完整 |

---

## 10. 群聊可贴：最关键差异（7 条）

1. **定位**：A=知识中台（+协同工作台）；B=FDE 应用交付中台（评测门禁与上线闭环是主叙事）。  
2. **向量底座**：A=Qdrant+进程内 BM25；B=Postgres pgvector+全文 RRF——运维与调参路径不同。  
3. **切块**：A 近补齐父子/语义共 3 策略；B 已产品化为 9 种方法 + 按文件配置 + 分块 QA/关键词增强。  
4. **应用编排**：A 已有 xyflow 多节点与 6 场景模板；B 强在版本/门禁/分享/API，Chat Flow 仍声明未上线。  
5. **质量闭环**：B 有评测集发布门禁与 Trace→Case 回流；A 有 RAG 工作台指标评测，但无同等「不通过不能发布」。  
6. **观测计费**：B 一等公民 Trace+cost；A 为 log/run/task 投影 MVP，计费无价表。  
7. **租户与协同**：B 有 Workspace/Token；A 无多租户但有 B 没有的需求—契约—BOM 协同。借鉴应「借治理与切块体验，不借换引擎、不丢协同」。

