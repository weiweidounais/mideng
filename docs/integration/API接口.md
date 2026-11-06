# 统一版本接口契约

本轮裁决：保留API接口，不接真实模型，以Codex执行功能测试。下列新接口均要求现有独立账号会话；写入要求X-CSRF-Token，持久写入另外要求X-Idempotency-Key。模型接口不能绕过资料权限。

基础路径：`/api/projects/{pid}/knowledge`。

| 方法与路径 | 输入 | 输出与错误 |
| --- | --- | --- |
| GET `/capabilities` | 无 | model_enabled=false、当前能力、模型预留接口路径 |
| GET/POST `/libraries` | POST: name, restricted默认true, readers账号ID数组 | 可读列表 / 新知识空间，含id/revision/domain=knowledge；越权401/403/404 |
| PUT `/libraries/{lid}` | name, restricted, readers, revision | 仅责任人维护；有效项目成员才能成为reader；409保留原值 |
| GET/POST `/libraries/{lid}/documents` | GET:page；POST:multipart file | 发布资料或本人草稿的分页摘要 / 持久排队的解析对象；支持UTF-8 MD/TXT/CSV、PDF、DOCX、XLSX，原件≤20MB |
| GET `/libraries/{lid}/documents/{did}` | 无 | 受当前共享/发布状态约束的片段与状态；路径不返回 |
| GET `/libraries/{lid}/documents/{did}/original` | 无 | 原件真实字节、哈希校验；未发布对非责任人404 |
| POST `/libraries/{lid}/documents/{did}/actions` | revision, action=publish/withdraw/retry | 新revision与状态；未完成解析不可发布，发布/下载核对原件哈希 |
| POST `/libraries/{lid}/search` | query | mode=keyword、最多20项原文来源；不调用模型、不生成答案 |
| POST `/libraries/{lid}/retrieve` | query | 预留向量检索：503、error.code=MODEL_NOT_CONFIGURED；授权检查先于此错误 |
| POST `/libraries/{lid}/chat/stream` | query | 预留模型对话：text/event-stream，终止event:error，code=MODEL_NOT_CONFIGURED；没有token或伪造答案 |
| GET/POST `/libraries/{lid}/applications` | POST:definition | 发布应用或责任人草稿列表 / 新草稿；仅开始、条件、模板、输出节点，拒绝尚未启用的检索/模型节点 |
| PUT `/libraries/{lid}/applications/{aid}` | definition, revision | 保存草稿，发布快照保留，旧修订号409 |
| POST `/libraries/{lid}/applications/{aid}/publish` | revision, cases:[{input,expectContains,expectStatus}] | 用例全部通过才发布；失败422且不覆盖旧发布快照 |
| POST `/libraries/{lid}/applications/{aid}/rollback` | revision, target_revision | 回退已发布快照，草稿保留，留审计记录 |
| POST `/libraries/{lid}/applications/{aid}/run` | input, mode=draft/published | 持久运行记录与逐节点结果；tokens=null；同幂等键回原结果；草稿限责任人 |
| GET `/libraries/{lid}/runs` | 无 | 本人最近运行记录；共享撤销后拒绝旧记录读取 |

错误采用现有 `error.code/message/request_id` 包装；请求恢复使用现有 `/api/requests/{key}`，知识对象增加domain=knowledge并重新检查当前项目、资料共享权限，不能因知道旧编号而绕过撤权。

后续模型启用需补齐：厂商、服务地址、实际模型、能力类型、预算、资料出口与超时/用量契约；凭证只在服务端加密或Secret中保存，不放到画布节点、前端、Git或日志。当前没有模型配置、外部请求或费用。旧代码中已有的模型适配器仍保留，但没有挂到本轮统一入口。
