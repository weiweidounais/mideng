# 云电脑运行说明

- 代码目录：`/workspace/enterprise-kb`
- 来源：Mac `~/Desktop/工作台/enterprise-kb`（密灯·企业知识中台）
- 启动命令：
  ```sh
  cd /workspace/enterprise-kb/backend
  uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8000
  ```
- 访问：云电脑浏览器打开 http://127.0.0.1:8000
- 健康检查：http://127.0.0.1:8000/api/health
- 管理口令：`backend/.runtime/bootstrap-passwords.json`（勿外传）
- 未拷贝：`node_modules`、`.venv`、RAG `models_cache`（约 91MB，可按需重建）

- 一期需求协同入口（侧栏「一期需求协同」）：
  - 需求交底包：http://127.0.0.1:8000/#/requirements
  - 接口契约台账：http://127.0.0.1:8000/#/contracts
  - 例外与待办：http://127.0.0.1:8000/#/exceptions
- 演示角色在页面顶部切换：市场 / 商务 / 项目经理 / 设计 / 采购；页面会按角色开放录入、交底、回写、契约状态与采购回复操作。
- 一期演示数据保存在当前浏览器 `localStorage`（键：`zhixu:demand-hub:v1`），不依赖后端；可在任一页面点「重置」恢复嘉元样例数据。
- 推荐演示顺序：市场录入需求 → 商务确认交底 → 设计回写方案 → 设计/采购维护 BOM 契约 → 采购登记料表/交期 → 项目经理在例外页查看断点。
- 原有知识库、在线对话、应用生成与 `/api/health` 保持不变。
