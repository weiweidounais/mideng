# 密灯 · 企业知识中台

企业知识导入、切块预览与元数据标注、向量检索与流式问答的本地可运行原型（FastAPI + LangChain + Qdrant + React）。

**默认入口：** http://127.0.0.1:8000/ · **API 文档：** http://127.0.0.1:8000/docs

> 本仓不含运行时口令与 `.runtime` 数据；首次启动会本地生成口令。请勿把 `backend/.runtime/` 或真实 `.env` 提交进 Git。

## RAG 能力扩展（2026-10-28）

已增加真实后端入口：http://127.0.0.1:8000/#/rag-workbench 。使用方式、已接入范围与 NVIDIA RAGAS 等待启用项见 [RAG 技能集成说明](integrations/README.md)。

# 密灯 · 企业知识中台 1.0

## 当前阶段：本地原型调整

2026-10-28 起，默认开发入口切为独立本地原型，先测试和修改界面，再按确认后的范围同步。已上传原件、真实业务数据库、后端代码与现有 `frontend/dist/` 保留。

```sh
cd "/Users/Apple_501/Desktop/工作台/enterprise-kb/frontend"
npm run dev
```

打开 `http://127.0.0.1:5173`。不需要启动 Python、数据库或云端模型。现有资料显示为一次只读快照的副本；在原型中保存、删除、上传、测试或发布只作用于浏览器本地副本，不会自动同步后端。模型、OCR 和问答结果会明确标为模拟，原件入口仅说明保留位置，不请求或修改真实原件。原型不保存真实 API Key 或管理口令。

本地修改保存在当前浏览器中，可通过“系统设置 → 导出原型副本”导出供后续审阅与同步。更换浏览器或清理站点数据前应先导出。原型角色可直接切换，用于验证界面体验。

`npm run build:prototype` 构建到 `dist-prototype/`，不会覆盖联调版本的 `dist/`。原有真实 API 模式保留为 `npm run dev:live`（5174，需自行启动真实后端），当前不启动，也不自动发布或迁移原型改动。

以下章节记录真实后端联调版本的运行方式，当前原型调整阶段无需执行。

前端原型已接入真实 FastAPI / LangChain 后端。提供文件导入、知识库、草稿检查/发布、Qdrant 向量检索、中文关键词融合、Rerank、流式问答、版本来源与日志。使用者免登录，两个管理角色以服务端口令进入。

当前本机已启动：前端开发地址 `http://127.0.0.1:5173`，API `http://127.0.0.1:8000`，API 文档 `http://127.0.0.1:8000/docs`。重启电脑后按以下方式启动。

## 本机启动

需要 Node.js 22+、Python 3.12 与 uv。仓库带 package-lock.json 和 uv.lock。

```sh
cd "/Users/Apple_501/Desktop/工作台/enterprise-kb"
./scripts/start-local.sh
```

此命令构建前端并由 API 同源提供网页，随后访问 \*\*<http://127.0.0.1:8000\*\*。开发前端时另开终端：>

```sh
cd frontend
npm ci
npm run dev
```

Vite 的 `/api` 会代理到本机 8000。实际运行数据位于 `backend/.runtime/`，不再把知识或模型凭证存入浏览器 localStorage。

**本地开发配置**：SQLite + Qdrant 本地持久化 + 单 API 进程中的持久任务执行器，适合这台未安装 Docker 的 Mac 联调。任务写数据库并在重启后恢复；不使用进程内假进度。Qdrant 本地目录仅供这个 API 进程使用，不可另开多进程或 Celery 并行访问。

## 第一次进入

首次启动会生成两个随机管理口令，保存到当前账户可读的：

`backend/.runtime/bootstrap-passwords.json`

其中 `admin` 对应管理员，`manager` 对应知识库管理人员。也可在首次启动前通过 `backend/.env` 的 `ADMIN_PASSWORD` / `MANAGER_PASSWORD` 指定至少 10 位口令。已有数据库不会因修改环境变量而覆盖既有口令。登录后可在系统设置修改口令。

原型的 `admin123` / `manager123` 已停用。使用者无需口令，但匿名会话仍由服务端 Cookie 隔离。切换角色不改变该浏览器的对话归属。

## 配置模型与云解析

管理员进入“模型与服务”后：

1. 点击“添加模型”，可在同一窗口填写服务商、API Key（api_key）、Base URL（base_url）、实际模型 ID（model）及模型类型。默认新建独立连接，也可复用已有连接。保存是原子操作，不自动调用云端。
2. 在“连接配置”显式测试认证，再测试具体 LLM、Embedding、Rerank、Vision 模型的能力。编辑模型会显示实际 Base URL；API Key 留空保留已有凭证。共享连接修改需要明确允许，更换已绑定向量空间仍需新建配置并重建索引。
3. Embedding 测试检测返回维度；如模型需要 `dimensions` 参数，在高级配置中明确启用。更换已绑定向量空间时要新建配置并重建索引，同维度也不能混用。
4. 阿里云百炼（通义 / 千问）、OpenRouter、AIHubMix 支持各自已接入任务；DeepSeek 官方连接只开放 LLM 与按型号核验的视觉能力，Embedding / Rerank 使用其他连接。
5. 阿里云 DocMind 填 **AccessKey ID / Secret**，与百炼 Key 分开。连接保存后不伪造 OCR 测试成功；实际文件解析后才能验证权限、服务开通与返回结构。

模型测试会真正发起小请求，按服务商规则计费。文档入库、图片理解、向量化、重排与问答也会产生实际用量。密钥加密存储在服务端，接口不返回明文，错误信息不回显密钥。

供应商未返回用量时日志显示“未知”，不记作零，不根据文本长度伪造 token；OCR 页数与模型 token 分别保留。可以关闭某型号的流式 usage 选项以兼容不支持该参数的 API。

## 实际使用路径

新建知识库 → 选择文件 → 设置解析/图意理解/自动发布 → 上传 → 在任务中心检查进度 → 查看真实知识片段 → 发布索引 → 检索测试 → 在线对话 → 点击来源 → 日志详情。

关闭自动发布时，普通文本/表格资料可在未配置 Embedding 前先解析并检查；发布索引才要求可用 Embedding。扫描 PDF、复杂图文和图片仍需要相应云解析/视觉服务；缺少配置会明确失败，不生成模拟内容。

支持 `.doc/.docx/.pdf/.md/.png/.jpg/.jpeg/.xlsx/.xls/.csv`。Word 标题、PDF 页码、表格 Sheet/行范围和图像资产尽可能保留。旧 `.doc` 的图片若云解析不提供可下载资源会显示警告；应检查真实文件样例。表格用于知识检索与来源引用，不执行工作簿宏或跨表精确计算。

同名文档可显式替换为新版本。发布前旧内容和原件继续服务，成功后切换，历史引用保留版本链接。停用/删除先在业务库排除检索，再清理向量，避免残留向量被召回。失败重试复用已解析草稿；云异步任务会记录任务 ID，避免无故重复提交收费解析。

## 应用生成与节点编排

“应用生成”提供节点画布。管理员与知识库管理人员可维护应用，使用者可运行已发布的应用。内置起始模板为知识问答、文案改写、规则分流；模板只提供结构，未配置的知识库/模型会明确提示。

操作路径：选择模板或新建空白应用 → 编辑节点与连线 → 保存草稿 → 校验 → 调试运行 → 检查逐步输出、引用、用量和耗时 → 发布。编辑草稿不会覆盖已经发布的版本，需要再次发布才生效。

支持开始、知识检索、模型生成、条件分支、文本模板、结果输出六类节点。条件节点有“满足 / 不满足”两条连线，仅执行实际选中的分支；支持拖动节点、删除连接、缩放画布和编辑节点参数。校验会检查环路、未连接节点、变量、所选模型与知识库配置。

节点过小时可进入“专注编辑”，以可读大小查看和拖动节点；“节点参数”按钮可展开或收起参数栏。

变量写法：`{{input}}` 为本次输入，`{{context}}` 为上游检索内容，`{{previous.output}}` 为实际执行的直接上游输出，`{{节点ID.output}}` 为指定上游节点输出。第一版为无环流程，不执行任意脚本或外部 HTTP 节点。

规则分流可以不依赖模型直接运行；检索和模型节点会调用配置的真实服务，按供应商返回记录用量，缺失显示未知。应用定义、发布快照和运行历史保存在服务端；普通使用者无法读取未发布草稿或其他浏览器的运行记录。

模型录入与应用板块的 [本轮验收记录](qa/workflows/验收记录.md) 包含实际界面和运行证据。

## 正式部署：已确认的方案 A

`compose.yaml` 提供 PostgreSQL 17 + Qdrant + Redis + Celery + API/前端同源部署，前后端仍是同一套业务代码。本机尚未安装 Docker，因此此部署组合尚未在本机实际启动验证。

```sh
cp .env.compose.example .env
# 修改 POSTGRES_PASSWORD、SECRET_KEY 及实际使用的浏览器来源地址。
docker compose up --build -d
```

访问 `http://localhost:8000`。如果供局域网同事访问，把实际地址（如 `http://192.168.x.x:8000`）加入 `ALLOWED_ORIGINS`；内网入口配置 HTTPS 时设置 `COOKIE_SECURE=true`。PostgreSQL/Qdrant/Redis 不映射宿主机端口。

首次口令位于应用数据卷，可由部署人员在本机读取 `docker compose exec api cat /data/bootstrap-passwords.json`。不要将输出、凭证文件或 `.env` 提交到代码仓库。

本机直接联调需开放局域网时使用 `KNOWLEDGE_HOST=0.0.0.0 ./scripts/start-local.sh`，并在 `backend/.env` 中设置真实来源地址。电脑休眠或关机会停止服务。

## 检查与验证

前端流式契约回归使用仓库已有的 Node.js / TypeScript，首次运行测试前先安装前端依赖：

```sh
cd frontend
npm ci
cd ../backend
uv sync --frozen
uv run pytest -q
cd ../frontend
npm run build
```

[后端验收记录](qa/backend/验收记录.md) 区分三种证据：实际本机文件/数据库验证、外部 HTTP 合同测试、待真实云凭证验证。测试不会使用用户凭证，也不会通过本地模型代替云端能力。

## 数据升级与备份

启动时运行 Alembic 迁移，初始迁移兼容已创建的同结构数据库。迁移脚本位于 `backend/migrations/`，锁定依赖后升级前应备份。

本地配置：先停止 API，等待导入任务退出，再完整备份 `backend/.runtime/`。其中包含数据库、原件、解析结果、Qdrant 本地数据和加密密钥；只复制 SQLite 主文件而忽略 WAL 或索引并不能保证完整恢复。

Compose 配置：停止 API/Worker 后，备份 PostgreSQL（pg_dump）、Qdrant 快照或已停止服务的数据卷，以及 application_data 文件卷。`SECRET_KEY` 或 encryption.key 必须随凭证备份保存，不能换一把密钥后期待旧凭证仍可解密。Redis 队列可由数据库任务记录重建；不要把它当唯一任务来源。

恢复时保持服务停止，恢复数据库、索引、文件与同一加密密钥，再启动并验证一份知识的来源、检索和问答。配置页的“导出配置快照”只导出脱敏配置，**不代替完整数据备份**。

## 代码位置

- `backend/app/security.py`：管理口令、匿名会话、权限与 CSRF。
- `backend/app/providers.py`：服务商适配、加密凭证和模型能力测试。
- `backend/app/parsers.py`：真实文件读取、云解析及视觉处理。
- `backend/app/ingestion.py`：上传、版本、任务恢复与索引发布。
- `backend/app/rag.py`：Qdrant、混合检索、重排、LangChain SSE 与日志。
- `frontend/src/api.ts` / `store.tsx`：真实 API、SSE 和服务端状态。
