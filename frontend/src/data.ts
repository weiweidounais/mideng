import type { KnowledgeBase, KnowledgeDoc, Chunk, LogEntry, ModelConfig, Connection } from './types';
export const initialKbs: KnowledgeBase[] = [
{id:'kb-policy',name:'企业制度手册',description:'让制度触手可及。涵盖行政流程、财务报销与企业管理规范。',category:'行政制度',color:'violet',tags:['制度规范','全员适用'],embedding:'text-embedding-v4',updatedAt:'10/26 09:32',status:'ready'},
{id:'kb-product',name:'产品与解决方案',description:'产品功能、使用指南与行业方案，快速找到每一个产品答案。',category:'产品知识',color:'blue',tags:['产品手册','解决方案'],embedding:'text-embedding-v4',updatedAt:'10/25 16:48',status:'ready'},
{id:'kb-tech',name:'技术研发文档',description:'开发规范、API 接口与系统架构，让团队经验持续沉淀。',category:'技术研发',color:'teal',tags:['接口文档','研发规范'],embedding:'text-embedding-v4',updatedAt:'10/25 14:20',status:'ready'},
{id:'kb-hr',name:'人力资源与成长',description:'从入职第一天到每一步成长，了解福利、培训与职业发展。',category:'人力资源',color:'orange',tags:['员工福利','新员工'],embedding:'text-embedding-v4',updatedAt:'10/24 11:05',status:'ready'},
{id:'kb-service',name:'客户服务知识',description:'常见问题、服务流程和排障指南，让每一次支持更有依据。',category:'客户服务',color:'pink',tags:['常见问题','服务支持'],embedding:'text-embedding-v4',updatedAt:'10/23 17:30',status:'ready'},
{id:'kb-brand',name:'品牌与市场',description:'集中管理品牌规范、市场资料与传播素材，保持一致表达。',category:'市场运营',color:'slate',tags:['品牌资料'],embedding:'text-embedding-v4',updatedAt:'10/26 09:00',status:'empty'}];
export function makeChunks(kind:string,name:string):Chunk[]{
 const location=kind==='pdf'?'第 3 页':kind==='xlsx'||kind==='xls'||kind==='csv'?'差旅标准 · A2:D6':kind==='md'?'开发规范 / 提交规范':kind==='png'||kind==='jpg'?'原图 · 流程区域':'第三章 / 差旅与费用';
 const topics: [RegExp,string,string,string][]=[
 [/产品|解决方案/,'产品能力与文件支持','知识平台支持 Word、PDF、Markdown、图片和 Excel / CSV 表格。PDF 可包含扫描页、文字、表格与图像。图表语义理解需配置独立视觉模型。','产品使用指南 / 文件导入'],
 [/开发|API|架构/,'研发协作与接口规范','开发分支使用 feature/功能名，修复分支使用 fix/问题描述。提交前进行类型检查与相关模块测试。API 接口应提供错误码、请求 ID 和清晰的输入校验。','开发规范 / 分支与提交'],
 [/入职|福利/,'新员工入职与福利','新员工入职需准备身份证明、学历证明与银行卡信息，按人事通知提交。入职当天由行政安排工位和设备，由直属负责人介绍团队协作流程。福利政策以正式员工手册为准。','员工手册 / 入职准备'],
 [/客户|排障/,'客户支持与问题排查','遇到使用问题，请先记录发生时间、操作步骤、错误提示和请求 ID。可先查看常见问题，仍未解决时联系内部服务支持人员；涉及敏感资料时请先脱敏。','客户服务 / 支持流程']];
 const topic=topics.find(([re])=>re.test(name));
 if(topic)return [{id:crypto.randomUUID(),title:topic[1],content:topic[2]+'（此为原型示例内容。）',location:kind==='pdf'?'第 2 页 · '+topic[3]:topic[3],kind:'text'},{id:crypto.randomUUID(),title:'资料维护与适用说明',content:'示例知识仅用于体验导入、检索与来源引用流程。正式使用时应由知识库管理人员检查文档版本、内容完整性和适用范围，并在发布后验证检索效果。',location:kind==='pdf'?'第 3 页':'使用说明 / 维护',kind:'text'}];
 return [{id:crypto.randomUUID(),title:'适用范围与基本要求',content:`《${name.replace(/\.[^.]+$/,'')}》示例片段：本规范适用于企业全体员工。出差前应完成出差申请，经直属负责人审批后执行。相关费用以真实业务发生、有效凭证和审批记录为依据。`,location,kind:'text'},
 {id:crypto.randomUUID(),title:'差旅费用标准',content:'项目 | 一线城市 | 其他城市\n住宿费 | 500 元/人/晚 | 350 元/人/晚\n餐饮补助 | 100 元/人/天 | 80 元/人/天\n市内交通 | 实报实销 | 实报实销\n以上为原型演示内容，不代表实际企业政策。',location:kind==='xlsx'?'差旅标准 · A2:D6':kind==='pdf'?'第 5 页 · 表 2':location,kind:'table'},
 {id:crypto.randomUUID(),title:'报销审批流程',content:'员工提交申请 → 直属负责人审批 → 财务审核 → 付款归档。若材料不完整，财务退回并提示补充。图像语义描述由视觉模型生成，需与原图核对。',location:kind==='pdf'?'第 6 页 · 图 1':location,kind:'image'}];
}
const fileRows=[['kb-policy','差旅及费用报销管理办法.pdf','pdf','2.4 MB'],['kb-policy','员工行为规范.docx','docx','486 KB'],['kb-policy','2026 差旅费用标准.xlsx','xlsx','128 KB'],['kb-policy','报销审批流程.png','png','864 KB'],['kb-policy','行政采购管理办法.doc','doc','340 KB'],['kb-product','产品使用指南.pdf','pdf','3.6 MB'],['kb-product','企业解决方案.docx','docx','760 KB'],['kb-product','产品功能清单.xlsx','xlsx','192 KB'],['kb-tech','开发规范.md','md','32 KB'],['kb-tech','API 接口参考.pdf','pdf','1.8 MB'],['kb-tech','系统架构说明.md','md','46 KB'],['kb-hr','新员工入职指南.pdf','pdf','1.2 MB'],['kb-hr','员工福利手册.docx','docx','620 KB'],['kb-service','客户常见问题.csv','csv','92 KB'],['kb-service','客户支持排障手册.pdf','pdf','1.6 MB']];
export const initialDocs:KnowledgeDoc[]=fileRows.map(([kbId,name,kind,size],i)=>({id:`doc-${i+1}`,kbId,name,kind,size,chunks:makeChunks(kind,name),status:'ready',updatedAt:'10/26 09:32',version:1}));
export const initialModels:ModelConfig[]=[
{id:'model-llm',name:'企业问答模型',modelId:'qwen-plus',provider:'阿里云百炼',type:'LLM',enabled:true,status:'connected',context:131072},
{id:'model-embed',name:'知识索引模型',modelId:'text-embedding-v4',provider:'阿里云百炼',type:'Embedding',enabled:true,status:'connected',dimension:1024},
{id:'model-rerank',name:'检索重排模型',modelId:'qwen3-rerank',provider:'阿里云百炼',type:'Rerank',enabled:true,status:'connected'},
{id:'model-vision',name:'图表理解模型',modelId:'qwen-vl-plus',provider:'阿里云百炼',type:'Vision',enabled:true,status:'connected',context:32768}];
export const initialConnections:Connection[]=[
{id:'con-ali',name:'阿里云百炼',provider:'阿里云百炼',baseUrl:'https://dashscope.aliyuncs.com/compatible-mode/v1',protocol:'OpenAI 兼容 + DashScope',enabled:true,status:'connected',keyConfigured:true},
{id:'con-or',name:'OpenRouter',provider:'OpenRouter',baseUrl:'https://openrouter.ai/api/v1',protocol:'OpenAI 兼容',enabled:false,status:'untested',keyConfigured:false},
{id:'con-hub',name:'AIHubMix',provider:'AIHubMix',baseUrl:'https://aihubmix.com/v1',protocol:'OpenAI 兼容',enabled:false,status:'untested',keyConfigured:false},
{id:'con-ds',name:'DeepSeek',provider:'DeepSeek',baseUrl:'https://api.deepseek.com/v1',protocol:'OpenAI 兼容',enabled:false,status:'untested',keyConfigured:false},
{id:'con-ocr',name:'阿里云 DocMind',provider:'阿里云 DocMind',baseUrl:'docmind-api.cn-hangzhou.aliyuncs.com',protocol:'阿里云 SDK · AccessKey',enabled:true,status:'connected',keyConfigured:true}];
export const initialLogs:LogEntry[]=Array.from({length:8},(_,i)=>({id:`req-demo-${1008-i}`,question:['出差报销需要哪些材料？','新员工入职需要准备什么？','产品支持哪些文件类型？','出差住宿费用标准是多少？','开发分支如何命名？','报销被退回后怎么处理？','查询本月销售总额','如何联系客户支持？'][i],answer:i===6?'当前知识库未找到足够依据。':'根据知识库内容，相关要求见所引用的制度与操作规范。此为交互演示。',model:'qwen-plus',kbName:['企业制度手册','人力资源与成长','产品与解决方案','企业制度手册','技术研发文档','企业制度手册','企业制度手册','客户服务知识'][i],status:i===5?'degraded':'success',tokens:1426+i*213,inputTokens:1000+i*170,outputTokens:426+i*43,duration:2.34+i*.36,firstToken:.92+i*.1,time:`10/26 ${['10:42','10:36','10:28','10:15','09:58','09:46','09:32','09:20'][i]}`,role:'使用者',source:'chat',steps:[{name:'向量与关键词检索',model:'text-embedding-v4',duration:.24,tokens:28,status:'成功'},{name:'结果重排',model:'qwen3-rerank',duration:.18,tokens:120,status:i===5?'超时，已降级':'成功'},{name:'生成回答',model:'qwen-plus',duration:1.92+i*.36,tokens:1426+i*213,status:'成功'}]}));
