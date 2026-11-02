# 原型 → 实现 缺口全表（知序）

> 依据：`frontend/src`（含 `prototype/`）、`backend/app`、`README.md`、`integrations/README.md`、`applications-contract.md`  
> 状态标注：**已有** / **部分** / **缺口** / **原型模式差异** / **待验证**  
> 「未实现」指相对产品原型愿景或工作群五项需求仍缺的生产能力；已上线能力也列入以便对照。

---

## A. 知识库

| 项 | 状态 | 证据 / 说明 |
|----|------|-------------|
| 知识库 CRUD、分类/标签/颜色 | 已有 | `ingestion.py` LibraryCreate/Patch；`Knowledge.tsx` |
| 绑定 Embedding、切换模型触发重建 | 已有 | `pendingEmbedding` + reindex 任务 |
| 文档上传、多格式解析、版本替换 | 已有 | ALLOWED 扩展名；`replaceDocumentId` |
| 草稿检查 / 发布索引 / 停用删除 | 已有 | draftChunks → publish；向量清理 |
| 原件下载与预览 | 已有（live） | `/documents/{id}/original`；原型不读原件 |
| 检索测试（hybrid/semantic/keyword + rerank） | 已有 | Knowledge 检索页签 + `rag.retrieve` |
| 知识库级 ACL / 部门隔离 | 缺口 | 仅角色 admin/manager/user；无库级权限模型 |
| 跨库统一目录 / 目录树管理 | 缺口 | 扁平库列表 |
| 业务元数据（主体/负责人/关键词/预估问题） | 缺口 | 见 demand §3 |
| 文档级评论/批注协同 | 缺口 | 协同模块是交底/BOM，非知识批注 |
| 定时同步外部网盘/Confluence | 缺口 | 仅本地上传 |

## B. 导入与切块

| 项 | 状态 | 证据 / 说明 |
|----|------|-------------|
| auto/cloud 解析、图意理解、chunkSize | 已有 | Form + `parsers.parse_file` |
| DocMind OCR、Vision 描述 | 已有 | 需配置；失败不造假 |
| 任务中心进度/重试/取消 | 已有 | tasks + worker |
| 父子切分 | 缺口 | 仅 RecursiveCharacterTextSplitter |
| LLM 语义切分 | 缺口 | 无 |
| 切分策略 UI / API 字段 | 缺口 | 仅 chunkSize |
| 导入预览真实解析结果（提交前） | 部分 | 原型/前端用示例预览；真解析在上传后任务中 |
| 音视频转写、MinerU 全链路 | 缺口 | `integrations/README`「尚未启用」 |
| Claude/上游元数据增强 | 缺口 | 同上 |

## C. 检索与问答

| 项 | 状态 | 证据 / 说明 |
|----|------|-------------|
| 混合检索 + BM25 + Rerank + SSE 对话 | 已有 | `rag.py` |
| 来源引用抽屉、反馈 up/down | 部分 | 来源已有；反馈字段在类型中，后端持久化深度 **待验证** |
| 多轮上下文压缩 / 会话摘要 | 缺口 | 会话存消息，未见摘要链路 |
| Agent 工具调用 / Skill 编排问答 | 缺口 | 对话为「检索→生成」；无通用 Agent Harness |
| Guardrails / 幻觉评测进线上 | 部分 | 工作台批量评测有；线上问答无自动评测门禁 |
| NVIDIA RAGAS 完整分 | 缺口 | 需 Blueprint；未启用 |
| 对话权限：用户不可见他人会话 | 已有 | owner 隔离（代码路径） |

## D. 应用工作流

| 项 | 状态 | 证据 / 说明 |
|----|------|-------------|
| 六类节点画布、校验、发布、运行 | 已有 | applications.py + Applications.tsx |
| 模板：知识问答 / 文案改写 / 规则分流 | 已有 | templateInfo |
| 报告撰写场景模板 | 缺口 | 需求 1 |
| 审核场景（含人审节点） | 缺口 | 需求 1 |
| HTTP/代码/循环/子流程节点 | 缺口 | 合同写明无脚本、无外部 HTTP、无环 |
| 应用级权限与审计导出 | 部分 | 运行历史按 caller；无独立审计台账 UI |
| 应用运行并入统一观测中心 | 缺口 | 本轮仅原型草图 |

## E. 协同

| 项 | 状态 | 证据 / 说明 |
|----|------|-------------|
| 交底包 / 契约 / BOM / 例外看板 | 已有（后端+前端） | `collaboration.py` + Collaboration 及相关页 |
| 与知识库/问答深度打通（交底自动入库） | 缺口 | 独立 board API |
| 飞书/企微通知闭环 | 缺口 | 无连接器出站 |
| 需求/契约独立路由页 | 部分 | App 将 requirements/contracts/exceptions 并入 CollaborationPage；另有 `Requirements.tsx`/`Contracts.tsx`/`Exceptions.tsx` 是否仍挂载 **待验证**（App 当前未 lazy 这些独立文件） |

## F. 模型与运维

| 项 | 状态 | 证据 / 说明 |
|----|------|-------------|
| 多供应商连接、能力测试、本地向量 | 已有 | providers + Operations ModelsPage |
| SenseNova / 百炼多模态 embedding 等修复 | 已有 | integrations README 2026-10-28 |
| 模型路由策略（成本/延迟自动选模） | 缺口 | 人工选择 |
| 密钥轮换审计 UI | 部分 | 加密存储；无完整审计时间线产品页 |
| 系统设置（并发、限额、口令） | 已有 | SettingsPage + core settings |

## G. 观测与计费

| 项 | 状态 | 证据 / 说明 |
|----|------|-------------|
| 请求日志列表 + 步骤 + token（供应商为准） | 已有 | LogsPage + `log` 实体；来源 chat/retrieval/import |
| 导出 CSV | 已有 | LogsPage |
| 知识库构建过程专项观测台 | 缺口 | import 有 log source，但无构建流水线可视化中心 |
| Agent 调用字段（工具/Skill/Harness 异常） | 缺口 | 无 Agent 运行时 |
| 对话日志与应用 run 统一视图 | 缺口 | 两套存储 |
| 计费账本（按租户/模型/场景汇总、预算告警） | 缺口 | 仅日志汇总已知 tokens；无计价单价与账单 |
| 可观测「观测中心」导航与信息架构 | 部分→本轮补原型 | 原仅「日志与监测」；新增 Observability 页骨架 |

## H. RAG 能力工作台

| 项 | 状态 | 证据 / 说明 |
|----|------|-------------|
| 入库审计、Vault 导出、批量评测、本地引擎 | 已有（live） | rag_workbench.py；需 manager |
| 原型模式入口 | 原型模式差异 | App 在 prototype 隐藏 rag-workbench nav；页内提示走 8000 |

## I. 原型模式差异（`MODE=prototype`）

| 项 | 行为 |
|----|------|
| 数据 | `prototype/api.ts` 浏览器本地副本；不写真实后端 |
| 角色 | 免密码切换 |
| 模型/OCR/问答 | 明确模拟；tokens 常为 null |
| 原件 | 不读不改已上传原件 |
| 密钥 | 不保存 |
| 构建产物 | `dist-prototype/` 与 live `dist/` 分离 |
| 协同/观测等新页 | 可在原型演示；与后端同步需另开 live 与确认范围 |

## J. 部署与工程

| 项 | 状态 | 说明 |
|----|------|------|
| 本地 SQLite + 内嵌任务 | 已有 | start-local |
| Compose PG+Qdrant+Redis+Celery | 部分 | 文件在；本机 Docker「尚未实际启动验证」（README） |
| 多租户 SaaS | 缺口 | 单工作空间假设 |
| 移动端完整适配 | 部分 | 有窄屏 CSS；非独立 App |

---

## 补充材料

同目录 `002_缺口清单_原型到实现.md` 为并行细粒度盘点（约 66 条）；本表按模块归纳五项需求视角。冲突时以仓库代码 + 本机本轮改动为准。

## 与工作群五项的映射

1. 应用扩展 → D + demand §1  
2. 父子/语义切块 → B  
3. 自动元数据 → A/B + demand §3  
4. 本表全文  
5. 观测 → G + `observability-design.md` + 前端 Observability 页
