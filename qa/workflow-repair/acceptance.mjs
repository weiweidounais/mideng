const t=await taskSpace(5), p=t.page('p1');
const fs=await import('node:fs/promises');
const root='/Users/Apple_501/Desktop/工作台/enterprise-kb/qa/workflow-repair';
const s=JSON.parse((await p.fetch('/api/session')).body), headers={'X-CSRF-Token':s.csrf,'Content-Type':'application/json'};
const kb='a6f036b0-14b9-45ff-97c7-f93978c04869';
const p1='11035a02-215a-4df8-b470-68f8abda68eb',p2='4d58fb50-633e-4733-850f-cd90165bb1d9',p3='6f21f130-8693-4ebe-a34b-074449d5debe';
const cases=[
 {query:'信誉分每天最多恢复多少分？',expectedDocIds:[p1],answer:'正常对局每局恢复1分，每天最多3分，最高100分。'},
 {query:'信誉分低于80分可以参加哪些对局？',expectedDocIds:[p1],answer:'只能参加人机对战。'},
 {query:'第一次使用外挂会受到什么处罚？',expectedDocIds:[p2],answer:'封号30天，并清空本赛季段位。'},
 {query:'举报后多久收到处理结果？',expectedDocIds:[p3],answer:'24小时内通过系统消息通知。'},
 {query:'封号申诉需要提交什么资料，多久回复，同一次处罚能申诉几次？',expectedDocIds:[p3],answer:'账号ID、处罚时间、申诉理由，可附录像或截图；3个工作日内回复；同一次处罚只能申诉1次。'},
 {query:'辱骂其他玩家会扣多少信誉分，还会受到什么处罚？',expectedDocIds:[p1,p2],answer:'每次扣3分，并禁言1至7天。'}];
await fs.writeFile(root+'/cases.json',JSON.stringify(cases,null,2));
const r=await p.fetch(`/api/rag-workbench/knowledge-bases/${kb}/evaluations`,{method:'POST',headers,body:JSON.stringify({cases,topK:5,mode:'hybrid',rerank:true,engine:'platform'}),timeout:240000});
await fs.writeFile(root+'/retrieval-evaluation.json',r.body);console.log({evaluationStatus:r.status,report:JSON.parse(r.body).summary,rows:JSON.parse(r.body).rows?.map(r=>({query:r.query,status:r.status,recall:r.recall,error:r.error}))});
