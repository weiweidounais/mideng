# 002 产品展示名 →「密灯」重命名清单

> 日期：2026-10-30（Asia/Shanghai）  
> 范围：`/workspace/enterprise-kb` 面向用户的「知序」「知枢」「enterprise-kb」「002」展示名盘点。  
> 原则：**本清单只列路径 + 建议替换**；包名 / import / 历史设计稿文件名不强改。纯展示字符串（README 标题、页面 title、品牌区、助手署名、导出文件名前缀、FastAPI title）本轮已直接改为「密灯」。

## 命名约定（建议）

| 旧展示名 | 建议新展示名 | 备注 |
| --- | --- | --- |
| 知序 · 企业知识中台 | 密灯 · 企业知识中台 | 主产品名 |
| 知序 | 密灯 | 短名 / 品牌区 |
| 知序助手 | 密灯助手 | 对话署名 |
| 知序 Knowledge Hub | 密灯 Knowledge Hub | 页脚英文副标可保留 Hub，中文主名改密灯 |
| 知枢（本仓 docs/观测语境） | 密灯 | 勿与公开仓 zhishu-rag-platform「知枢」混淆 |
| 002（项目代号口头称呼） | 密灯 | 文档标题可逐步改；历史文件名 `002_*` 可暂留 |
| enterprise-kb（目录/仓名） | 暂不改 | 路径与部署目录；仅文案提及可写「密灯（enterprise-kb）」 |
| `zhixu-knowledge-hub` / `zhixu-backend` | **不要擅自改** | npm / Python 包名，改则牵涉依赖与脚本 |

---

## A. 本轮已直接改的纯展示字符串

| 路径 | 原展示文案（摘要） | 已改为 |
| --- | --- | --- |
| `README.md` L5 | `# 知序 · 企业知识中台 1.0` | `# 密灯 · 企业知识中台 1.0` |
| `frontend/index.html` | title / meta description「知序…」 | 「密灯…」 |
| `frontend/src/App.tsx` | Brand「知序」、欢迎页/页脚/帮助抽屉「知序 · 企业知识中台」「知序 Knowledge Hub」 | 「密灯…」 |
| `frontend/src/pages/Chat.tsx` | `知序助手` | `密灯助手` |
| `frontend/src/pages/Operations.tsx` | 导出 `知序-请求日志.csv` / `知序-配置快照.json` | `密灯-…` |
| `backend/app/main.py` | `FastAPI(title="知序 · 企业知识中台")` | `密灯 · 企业知识中台` |
| `CLOUD_RUN.md` | 「知序·企业知识中台」 | 「密灯·企业知识中台」 |
| `qa/workflows/验收记录.md` | 「项目：知序企业知识中台」 | 「项目：密灯企业知识中台」 |

---

## B. 建议改、本轮未动（历史文档 / 讨论稿，避免大面积改业务叙述）

| 路径 | 出现处摘要 | 建议替换文案 |
| --- | --- | --- |
| `docs/observability-design.md` | `产品：知序（enterprise-kb）` | `产品：密灯（enterprise-kb）` |
| `docs/002_可观测模块设计_知枢.md` | 标题「002 … · 知枢」；「现有知枢」 | 标题「密灯 可观测模块设计」；正文「现有密灯」；**文件名可暂留** |
| `docs/002_切块与元数据与场景扩展.md` | 标题「002 …」；交叉引用知枢稿 | 标题改为「密灯 切块…」；引用文件名可仍写旧路径并加注 |
| `docs/002_缺口清单_原型到实现.md` | 「Obsidian `002_知序企业知识中台`」 | 「Obsidian `密灯企业知识中台`」（外部笔记需人工同步） |
| `docs/002_vs_zhishu-rag-platform_差异讨论.md` | A 侧「知序」「知枢」「002」 | 统一写「A = 密灯（本地 enterprise-kb）」；对比对象 B 仍称公开仓「知枢」 |
| `docs/demand-five-items.md` | 标题「知序 / enterprise-kb」 | 「密灯 / enterprise-kb」 |
| `docs/prototype-implementation-gap.md` | 标题「（知序）」 | 「（密灯）」 |
| `docs/observability-design.md` L153 | 文件名提及「知枢」 | 可保留文件名引用，旁注「现产品名密灯」 |

---

## C. 不要改（非展示 / 易破坏）

| 路径或模式 | 原因 |
| --- | --- |
| `frontend/package.json` → `name: zhixu-knowledge-hub` | 包名；改需同步脚本与发布约定 |
| `backend/pyproject.toml` → `name: zhixu-backend` | 同上 |
| 目录名 `enterprise-kb`、compose 服务名、Python 模块路径 | 部署与 import |
| `frontend/src/demand/seed.ts` 中 `pkg-jy-002` / `REQ-JY-2026-002` | 业务样例编号，不是产品名 |
| `integrations/upstream/**`、perf-baseline 数值里的 `002` | 上游 ADR / 浮点噪声，非产品名 |
| `frontend/dist-prototype/**` | 构建产物；改源码后重新 `build:prototype` 即可 |
| `server.log` | 运行日志，勿手改 |
| `qa/**/*.json` 里绝对路径与评测快照 | 历史评测数据；新产品测另建集 |

---

## D. 前端构建产物提醒

`frontend/dist-prototype/index.html` 仍含旧 title「知序」。本轮只改源 `frontend/index.html`；下次原型构建会带上「密灯」。

---

## E. 与公开仓「知枢」的边界

公开 GitHub `zhishu-rag-platform` README 仍称「知枢 · AI 应用中台」。本仓改名「密灯」后，差异讨论稿应明确：**密灯 ≠ 公开仓知枢**，避免群内继续混称。

---

## F. 建议落地顺序（编码侧）

1. 确认本轮已改展示字符串在本地原型 / live 可见。  
2. 历史 `docs/002_*` 标题按需批量改（或只在文首加「现产品名：密灯」）。  
3. 包名 `zhixu-*` 另开任务评估，不与本轮素材准备绑死。  
4. 用 `docs/testdata-mideng/` 自造语料 + Mac「AI客服」真资料做导入与问答回归。

---

## G. 协作边界（2026-10-30 对齐）

- **本机编码**负责继续改名「密灯」、优化与 `qa/fixtures/mideng/` 真资料。  
- **素材侧**本清单只作路径+建议替换；**不再继续改前端/业务代码**，以免与本机编码撞车。  
- 上文「A. 本轮已直接改」记录的是素材侧曾改过的纯展示字符串；若本机编码有更新，以编码侧为准并回写本表。  
- 自造评测语料仅在 `docs/testdata-mideng/`，避开 `qa/fixtures/mideng/`。
