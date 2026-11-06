import type {RuleDefinition} from '../pilot/RuleCanvas';
export const purchaseSteps=[
 {title:'设计方案待确认',role:'设计',action:'确认演示方案'},
 {title:'项目经理提采购需求',role:'项目经理',action:'提交演示采购需求'},
 {title:'采购待接单',role:'采购',action:'接收演示采购需求'},
 {title:'采购执行',role:'采购',action:'提交演示下单结果'},
 {title:'项目经理复核数量与交期',role:'项目经理',action:'确认订购数量与约定到货时间'},
 {title:'质量等待实际到货',role:'采购',action:'登记演示到货'},
 {title:'到货质量验收',role:'质量',action:'确认演示材料合格'},
 {title:'商务合同与成本归档',role:'商务',action:'归档演示合同与采购成本'},
] as const;
export const traceSteps=[
 {title:'材料批次',role:'工厂'},{title:'焊缝与人员',role:'工厂'},{title:'预制记录',role:'工厂'},
 {title:'检测放行',role:'质量'},{title:'发运',role:'工厂'},{title:'安装',role:'现场'},
 {title:'试压记录',role:'现场'},{title:'试压确认',role:'质量'},{title:'质量确认完成',role:'质量'},
] as const;
export function advance(step:number,role:string,flow:readonly {role:string}[],blocked=false){
 if(blocked)throw new Error('演示来源已变更，请先完成变更处置。');
 if(step>=flow.length)throw new Error('本条演示流程已完成。');
 if(role!==flow[step].role)throw new Error('请先切换至'+flow[step].role+'演示角色。');
 return step+1;
}
export const initialRule:RuleDefinition={name:'材料到货处理建议',nodes:[
 {id:'start',kind:'start',label:'输入事项',config:{},position:{x:0,y:100}},
 {id:'text',kind:'template',label:'组织处理建议',config:{template:'处理建议：{{input}}。请由项目责任人核对。'},position:{x:240,y:100}},
 {id:'out',kind:'output',label:'输出',config:{template:'{{previous.output}}'},position:{x:480,y:100}},
],edges:[{id:'s-t',source:'start',target:'text'},{id:'t-o',source:'text',target:'out'}]};
export function runRule(d:RuleDefinition,input:string){
 if(!input.trim())throw new Error('请填写演示输入。');
 if(d.nodes.length>50)throw new Error('演示最多支持50个节点。');
 const map=new Map(d.nodes.map(n=>[n.id,n]));if(map.size!==d.nodes.length)throw new Error('节点编号不能重复。');
 const starts=d.nodes.filter(n=>n.kind==='start'),ends=d.nodes.filter(n=>n.kind==='output');
 if(starts.length!==1||ends.length!==1)throw new Error('流程须包含一个开始和一个输出。');
 const incoming=new Map(d.nodes.map(n=>[n.id,d.edges.filter(e=>e.target===n.id)]));
 const outgoing=new Map(d.nodes.map(n=>[n.id,d.edges.filter(e=>e.source===n.id)]));
 if(d.edges.some(e=>!map.has(e.source)||!map.has(e.target)))throw new Error('连线引用了不存在的节点。');
 if(incoming.get(starts[0].id)!.length||outgoing.get(ends[0].id)!.length)throw new Error('开始和输出的连接方向不正确。');
 for(const n of d.nodes){if(n.kind==='condition'&&outgoing.get(n.id)!.map(e=>e.sourceHandle).sort().join(',')!=='false,true')throw new Error('条件节点需要满足和不满足两条分支。');}
 const identities=d.edges.map(e=>e.source+'|'+e.target+'|'+(e.sourceHandle??''));if(new Set(identities).size!==identities.length||new Set(d.edges.map(e=>e.id)).size!==d.edges.length)throw new Error('连接不能重复。');
 const walk=(id:string,reverse=false)=>{const seen=new Set<string>(),todo=[id];while(todo.length){const here=todo.pop()!;if(seen.has(here))continue;seen.add(here);for(const e of (reverse?incoming:outgoing).get(here)!)todo.push(reverse?e.source:e.target);}return seen.size;};
 if(walk(starts[0].id)!==d.nodes.length||walk(ends[0].id,true)!==d.nodes.length)throw new Error('每个节点都须从开始连接到输出。');
 const pending=new Set(map.keys()),values=new Map<string,string>(),active=new Set<string>();let answer='';let reached=0;
 while(pending.size){let progress=false;for(const id of [...pending]){
  const edges=incoming.get(id)!;if(edges.some(e=>pending.has(e.source)))continue;
  progress=true;pending.delete(id);const n=map.get(id)!;const chosen=edges.filter(e=>active.has(e.id));
  if(n.kind!=='start'&&!chosen.length)continue;reached++;
  const previous=chosen.map(e=>values.get(e.source)??'').join('\n');
  const render=(s:string)=>s.replace(/\{\{\s*(input|previous.output)\s*\}\}/g,(_,key)=>key==='input'?input:previous);
  let result='';
  if(n.kind==='start')result=input;
  else if(n.kind==='condition'){const source=render(n.config.source??'{{input}}'),v=n.config.value??'';if(!v)throw new Error('请填写条件比较词。');result=String(n.config.operator==='equals'?source===v:n.config.operator==='not_contains'?!source.includes(v):source.includes(v));}
  else if(n.kind==='template'||n.kind==='output')result=render(n.config.template??'');
  else throw new Error('公开演示只支持本地规则节点。');
  if(result.length>100000)throw new Error('演示结果过长，请缩短模板。');
  values.set(id,result);if(n.kind==='output')answer=result;
  for(const e of outgoing.get(id)!)if(n.kind!=='condition'||e.sourceHandle===result)active.add(e.id);
 }if(!progress)throw new Error('流程包含循环，无法运行。');}
 if(!values.has(ends[0].id)||!answer)throw new Error('没有可到达的有效输出，请核对连线。');
 return {output:answer,steps:reached};
}
export type KnowledgeDocument = {id:string;title:string;text:string;source:string} & ({kind:'sample'} | {kind:'temporary';original:File;fingerprint:string});
export const demoDocs:KnowledgeDocument[]=[
 {id:'policy',kind:'sample',title:'材料采购与到货验收示例',text:'项目经理核对订购数量与约定到货时间。质量人员在材料实际到货后验收，验收合格再交商务归档采购合同与成本。',source:'合成制度 · 第1节'},
 {id:'change',kind:'sample',title:'项目变更协作示例',text:'设计、成本、进度、质量分别核对影响，登记批准依据。通知送达与本人确认分开记录，逐个对象完成处置后由项目经理关闭变更。',source:'合成制度 · 第2节'},
];
