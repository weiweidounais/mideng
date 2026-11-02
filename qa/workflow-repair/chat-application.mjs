const p=(await taskSpace(5)).page('p1');const fs=await import('node:fs/promises');
const root='/Users/Apple_501/Desktop/工作台/enterprise-kb/qa/workflow-repair';
const s=JSON.parse((await p.fetch('/api/session')).body), headers={'X-CSRF-Token':s.csrf,'Content-Type':'application/json'};
const kb='a6f036b0-14b9-45ff-97c7-f93978c04869';
const checks=[{question:'信誉分每天最多恢复多少分？',model:'3ffbb217-d4c8-43f8-a463-582eb5b2bf71'}, {question:'辱骂其他玩家会扣多少信誉分，还会受到什么处罚？',model:'190c7114-9085-47d4-9cea-765d901ccdaf'}, {question:'封号申诉需要提交什么资料，多久回复，同一次处罚能申诉几次？',model:'190c7114-9085-47d4-9cea-765d901ccdaf'}, {question:'这款游戏的会员年费是多少钱？',model:'190c7114-9085-47d4-9cea-765d901ccdaf'}];
for (const [i,item] of checks.entries()) {
 const r=await p.fetch('/api/chat/stream',{method:'POST',headers,body:JSON.stringify({kbIds:[kb],question:item.question,modelConfigId:item.model}),timeout:120000});
 await fs.writeFile(root+`/chat-${i+1}.sse`,r.body);
 const done=r.body.split('\n\n').find(x=>x.startsWith('event: done'));
 if(!done){console.log({question:item.question,http:r.status,error:r.body.slice(-400)});continue;}
 const data=JSON.parse(done.split('\ndata: ')[1]);
 await fs.writeFile(root+`/chat-${i+1}.json`,JSON.stringify(data,null,2));
 console.log({question:item.question,status:data.log?.status,answer:data.message?.content,sources:data.message?.sources?.map(s=>s.title),model:data.log?.model});
}
const definition={name:'小峡客服 · RAG 联调验收',description:'使用三份规则资料验证检索、重排、模型生成和引用。',nodes:[
 {id:'start',kind:'start',label:'用户问题',position:{x:30,y:160},config:{}},
 {id:'knowledge',kind:'knowledge',label:'检索规则资料',position:{x:300,y:160},config:{kbIds:[kb],query:'{{input}}',topK:5,minScore:.3,rerank:true}},
 {id:'answer',kind:'llm',label:'SenseNova 有据回答',position:{x:580,y:160},config:{modelConfigId:'190c7114-9085-47d4-9cea-765d901ccdaf',prompt:'只根据以下知识片段回答问题，每个事实引用对应编号，不虚构。无依据则说明资料未提供。\n问题：{{input}}\n资料：{{context}}',requireEvidence:true,maxOutput:2048}},
 {id:'output',kind:'output',label:'返回答案',position:{x:860,y:160},config:{template:'{{answer.output}}'}}],edges:[{id:'e1',source:'start',target:'knowledge'},{id:'e2',source:'knowledge',target:'answer'},{id:'e3',source:'answer',target:'output'}]};
const existing=JSON.parse((await p.fetch('/api/applications')).body).find(a=>a.name===definition.name);
const create=existing||JSON.parse((await p.fetch('/api/applications',{method:'POST',headers,body:JSON.stringify(definition)})).body);
await fs.writeFile(root+'/application.json',JSON.stringify(create,null,2));
if(create.id){const r=await p.fetch(`/api/applications/${create.id}/run`,{method:'POST',headers,body:JSON.stringify({input:'第一次使用外挂会受到什么处罚？如果有异议应该如何申诉？',mode:'draft'}),timeout:120000});await fs.writeFile(root+'/application-run.json',r.body);const d=JSON.parse(r.body);console.log({appId:create.id,http:r.status,status:d.status,output:d.output,error:d.error,steps:d.steps?.map(x=>({name:x.label,status:x.status}))});}
