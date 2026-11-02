# Applications API

All endpoints are under `/api`. Existing session cookies, CSRF tokens and role dependencies apply.

- `GET /applications`: array; managers/admins see drafts and graph definitions, users only published metadata.
- `POST /applications`: full draft `{name, description?, nodes, edges}`; 201.
- `GET /applications/{id}`: full draft for managers/admins; published metadata only for users.
- `PATCH /applications/{id}`: full draft plus optional `expectedRevision`; 409 on a supplied revision mismatch. Publishing is a separate action.
- `DELETE /applications/{id}`: manager/admin, 204; active executions prevent deletion.
- `POST /applications/{id}/validate`: `{valid, errors:[{nodeId?, message}]}`. Incomplete drafts may be saved; validation/publish/run enforce the entire graph and required resources.
- `POST /applications/{id}/publish`: snapshot validated current draft; 422 with joined validation errors on failure.
- `POST /applications/{id}/unpublish`: remove public availability while retaining editable draft.
- `POST /applications/{id}/run`: `{input, mode:'draft'|'published'}`; draft mode requires manager/admin. Defaults to published.
- `GET /applications/{id}/runs`: latest 100 runs owned by caller, or all for admins.

Run response: `{id,runId,applicationId,applicationName,revision,mode,input,status:'running'|'success'|'failed',output,sources,steps,tokens,duration,createdAt,finishedAt?,error?}`. Steps contain `{nodeId,label,kind,status:'success'|'failed'|'skipped',output,duration,tokens,meter:'local'|'cloud',error?,sources?,details?}`. Exceptions from model SDKs never go to the response. Cloud usage comes from vendor usage only; missing or purely local usage remains `null`.

Node shape: `{id,kind,label,position:{x,y},config:{...}}`; kind is start, knowledge, llm, condition, template or output. Edge shape `{id,source,target,sourceHandle?:'true'|'false'}`.

Configuration:

- start: `{}`
- knowledge: `{kbIds:string[],query?:'{{input}}',topK?:1..20,minScore?:0..1,rerank?:boolean}`
- llm: `{modelConfigId,prompt,temperature?:0..2,maxOutput?:1..131072,requireEvidence?:boolean}`
- condition: `{source?:'{{input}}',operator?:'contains'|'equals'|'not_contains',value:string}`
- template/output: `{template:string}`

Variables are literal substitution, never code evaluation. `{{input}}` is the original input; `{{context}}` contains executed knowledge ancestors; `{{previous.output}}` joins active direct predecessor outputs; `{{nodeId.output}}` references a named ancestor, and yields empty text for a skipped branch. Unknown, future or non-ancestor references fail validation. Node ID `previous` is reserved. Conditions need exactly one true and false edge; skipped branches never execute; merges run once if any incoming edge is active.

Only acyclic graphs with exactly one start and output are publishable. All nodes must be on a start-to-output path. There is a 50-node / 150-edge / 300KB definition cap, a 10K-character run input cap and 180-second execution deadline. Model nodes use real LangChain chains and enforce conservative UTF-8 byte budgeting for system, rendered input and reserved output. Byte budgeting is never reported as token usage. Runs share the chat concurrency pool. Published snapshots do not change when drafts are edited. Run histories are persisted separately from general chat logs.

Startup should call `recover_application_runs()` so interrupted executions become failed, rather than remaining running forever. No cloud models are bundled or downloaded. Actual cloud service accounts still require operator configuration and verification.

`llm.config.requireEvidence` defaults to false for general writing. When true and no executed knowledge ancestor supplied any context, the node returns the fixed local message “当前知识库未找到足够依据，请补充资料或调整问题。” with meter=local and tokens=null; no LLM request is made. The normal output node can consume this result. Knowledge Q&A templates should enable this option.
