# RAG 技能集成

访问 http://127.0.0.1:8000/#/rag-workbench ，使用管理员或知识库管理人员角色。

五个来源的技能安装在本项目 `.agents/skills/`。`sources.lock.json` 记录上游提交、文件校验和与接入范围；后续在本项目工作时可使用这些技能。`lyonzin/knowledge-rag` 是运行服务，安装的是其配套 `rag-evaluate-quality` 技能，并在独立虚拟环境安装实际服务。

## 当前可用

- 入库：沿用持久任务、SHA256 去重、版本化发布和 Qdrant，补充 TXT、JSON、HTML、PPTX、Notebook、代码文本。Notebook 不执行代码或索引输出；HTML 不执行脚本；PPTX 当前只读取文本与表格文本，图表/图片信息需核对原件。
- 入库检查：空内容、来源位置、重复原件、解析警告、发布状态。
- Markdown Vault：导出已发布内容的文字快照、frontmatter、来源位置和版本原件链接；不是原件备份，也不运行上游 `claude -p` 自动摘要或 MinerU。上游完整 local-vault 转换脚本原样保留。
- 本地引擎：真实 `knowledge-rag 4.11.1` + FastEmbed 中文 `BAAI/bge-small-zh-v1.5`（512 维）+ ChromaDB。管理端可显式包含待检查资料进行检索和评测，不改变业务文档状态；也可在“模型与服务”启用同一中文向量模型，绑定知识库后由正式 Qdrant 链路发布、检索和在线问答。两种索引分别维护。
- 批量评测：可选中台原有链路或本地引擎；预先标注参考文档，测量 Hit/Recall/MRR/nDCG，报告保存在业务数据库。K 是返回片段数，同文档重复片段不重复计相关性收益；失败项单独记录，语料变动时不生成聚合分数。关键词模式关闭重排不调用模型。
- NVIDIA 评测包：填写人工参考答案 answer 后导出 `corpus/` 原件 + `train.json`。原件路径受限，文件名与 contexts 对齐，避免文字重建丢失原始图表。

## 运行

后端在 `backend/` 启动：

```sh
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

本地后端启动时会检测并启动已安装的本地引擎，退出时仅关闭自己启动的子进程。如需独立运行，可在项目根目录另开终端：

```sh
./scripts/start-rag-engine.sh
```

适配服务仅监听 127.0.0.1:8011，通过仅本机账户可读的随机密钥接受业务 API 请求；一个进程拥有索引，不能对同一目录另开 writer。配置模板位于 `configs/knowledge-rag.yaml`，首次运行复制到 `backend/.runtime/knowledge-rag/config.yaml`；索引、模型缓存和密钥均在该运行目录。原有 Qdrant 与模型凭证不迁移、不覆盖。

首次使用：本地检索引擎 → 选择资料范围 → 同步 → 检索；然后使用相同资料范围进行本地引擎批量评测。文档变更、停用或删除后必须重新同步。新快照完整写入后才切换指针，查询前后都重新核对业务数据；旧快照保留在隔离目录中，不参与当前搜索。

## 尚未启用

NVIDIA rag-eval 面向 NVIDIA RAG Blueprint，当前中台接口与它不同。完整 RAGAS 执行仍需要 Blueprint 的 RAG/ingestor 服务、评审模型与 NVIDIA_API_KEY；本次没有运行这些外部服务或伪造忠实度/答案准确性分数。曾尝试获取 Blueprint 评测驱动源码，GitHub 网络连接失败；已安装的 NVIDIA 技能与完整操作参考不受影响。

local-vault 的音视频转写、MinerU OCR、Claude 元数据增强没有作为中台功能开放；当前新增格式及解析损失已在界面或文档警告中说明。

当前工作目录不含 Git 元数据，修改前源文件及已部署前端快照保存在 `qa/rag-integration/before/sources.tar.gz`。没有创建提交或 PR。

## 模型与流程修复（2026-10-28）

- SenseNova 官方 Token Plan 地址为 `https://token.sensenova.cn/v1`，与 OpenRouter 的凭证不通用。新增 SenseNova 和通用 OpenAI 兼容服务选项，支持读取服务端模型列表，完整 `/chat/completions` 地址会归一化为 Base URL。
- SenseNova Flash 支持对话和图片理解；重排通过显式对话评分适配，每批最多 8 个候选片段，验证索引、有限分数和输出截断。它不是专用向量模型。U 系列用于生图，不能当作文档图片理解配置。
- 千问 `qwen3-vl-embedding` 使用 DashScope 原生多模态向量接口，每批最多 20 段文本、禁用融合，按 index 验证并恢复输入顺序。需要百炼模型 API Key，DashVector 数据库 Key 无法调用此接口。
- 模型测试先验证连接；保存仍不调用模型。在线对话可明确选择已验证 LLM 并保存到会话，检索使用所选知识库保存的配置。
- 本地模型通过固定回环地址、独立服务密钥输出真实 ONNX 向量。正常发布后可直接用于在线对话、应用节点、检索测试和批量评测；本地计算不伪造云端 token 用量。
- 本轮测试素材为用户已有的 P1、P2、P3 原件，没有替换原件。验收记录位于 `qa/workflow-repair/`。

官方协议依据：[SenseNova API](https://github.com/OpenSenseNova/SenseNova6.8/blob/main/API.md)、[百炼多模态向量 API](https://help.aliyun.com/zh/model-studio/multimodal-embedding-api-reference)、[DashVector 与 DashScope 分别获取 Key](https://help.aliyun.com/zh/document_detail/2568028.html)。
