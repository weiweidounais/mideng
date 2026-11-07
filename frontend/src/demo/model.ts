import type {RuleDefinition} from '../pilot/RuleCanvas';
export const purchaseSteps=[
 {title:'设计发布落地方案',role:'设计',action:'发布演示落地方案'},
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
 if(role!=='管理员'&&role!==flow[step].role)throw new Error('请先切换至'+flow[step].role+'演示角色。');
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
 {id:'policy',kind:'sample',title:'材料采购与到货验收示例',text:'设计只提交落地实施方案。项目经理填写采购物品种类、规格、数量、单位和需用日期，并核对订购数量与约定到货时间。质量人员在材料实际到货后验收，验收合格再交商务归档采购合同与成本。',source:'合成制度 · 第1节'},
 {id:'change',kind:'sample',title:'项目变更协作示例',text:'设计、成本、进度、质量分别核对影响，登记批准依据。通知送达与本人确认分开记录，逐个对象完成处置后由项目经理关闭变更。',source:'合成制度 · 第2节'},
];

export type DemoItem={material:string;spec:string;quantity:string;unit:string;need_by:string};
export type DemoDemand={title:string;summary:string;source:string};
export type DemoScheme={title:string;notes:string;risks:string};
export type DemoOrderLine={quantity:string;eta:string};
export type BusinessState={demand:DemoDemand;demandPublished:boolean;scheme:DemoScheme;step:number;items:DemoItem[];ordered:DemoOrderLine[];supplier:string;difference:string;arrivals:DemoOrderLine[];contract:string;amount:string;archives:{title:string;items:DemoItem[];contract:string}[]};
export type BusinessCommand={kind:'demand';data:DemoDemand}|{kind:'publish-demand'}|{kind:'scheme';data:DemoScheme}|{kind:'request';items:DemoItem[]}|{kind:'next';ordered?:DemoOrderLine[];supplier?:string;difference?:string;confirmed?:boolean;contract?:string;amount?:string};
export function initialBusiness():BusinessState{return {demand:{title:'合成管段与材料协同需求',summary:'按现场条件完成安装，方案明确实施步骤、连接方式和风险；采购物品由项目经理核定。',source:'公开演示合成需求'},demandPublished:true,scheme:{title:'合成现场实施方案',notes:'核对现场路径与接口后分段施工，安装前检查连接条件，按适用工艺进行质量与试压核对。',risks:'合成方案仅展示协作路径，不作为真实施工依据。'},step:0,items:[],ordered:[],supplier:'',difference:'',arrivals:[],contract:'',amount:'',archives:[]};}
function requireRole(role:string,allowed:string[]){if(role!=='管理员'&&!allowed.includes(role))throw new Error('请切换至'+allowed.join('或')+'演示角色。');}
function requiredText(value:string,max:number){return !!value.trim()&&value.length<=max;}
function validDemoDate(value:string){const d=new Date(value+'T00:00:00Z');return /^\d{4}-\d{2}-\d{2}$/.test(value)&&!Number.isNaN(d.valueOf())&&d.toISOString().slice(0,10)===value;}
function quantityUnits(value:string){if(!/^\d+(\.\d{1,6})?$/.test(value)||value.replace(/^0+/,'').replace('.','').length>18)throw new Error('数量须大于0，最多18位数字和6位小数。');const [whole,fraction='']=value.split('.');const units=BigInt(whole)*1000000n+BigInt(fraction.padEnd(6,'0'));if(units<=0n)throw new Error('数量须大于0。');return units;}
export function validateDemoItems(items:DemoItem[]){if(!items.length||items.length>100)throw new Error('公开演示支持1—100种物品。');items.forEach((x,i)=>{if(!requiredText(x.material,120)||!requiredText(x.spec,200)||!requiredText(x.unit,20)||!validDemoDate(x.need_by))throw new Error('请补齐物品'+(i+1)+'的种类、规格、单位和需用日期。');quantityUnits(x.quantity);});}
export function transitionBusiness(state:BusinessState,role:string,command:BusinessCommand,blocked=false):BusinessState{
 const s=structuredClone(state);
 if(command.kind==='demand'){
  requireRole(role,['市场','商务']);if(s.step>0&&s.step<8)throw new Error('当前演示流程正在办理，请先完成或重置后再新建。');
  if(!requiredText(command.data.title,120)||!requiredText(command.data.summary,8000)||!requiredText(command.data.source,1000))throw new Error('请填写需求标题、正文和来源依据。');
  return {...initialBusiness(),demand:structuredClone(command.data),demandPublished:false,archives:s.archives};
 }
 if(command.kind==='publish-demand'){requireRole(role,['商务']);if(s.demandPublished)throw new Error('需求已经发布。');s.demandPublished=true;return s;}
 if(blocked)throw new Error('演示来源已变更，请先完成变更处置。');
 if(command.kind==='scheme'){
  requireRole(role,['设计']);if(!s.demandPublished||s.step!==0)throw new Error('商务发布需求后，设计才能发布本次落地方案。');
  if(!requiredText(command.data.title,120)||!requiredText(command.data.notes,8000)||command.data.risks.length>4000)throw new Error('请填写落地方案标题和实施内容，风险不超过4000字。');
  s.scheme=structuredClone(command.data);s.step=1;return s;
 }
 if(command.kind==='request'){
  requireRole(role,['项目经理']);if(s.step!==1)throw new Error('设计发布落地方案后，项目经理才能填写并提交采购需求。');validateDemoItems(command.items);
  s.items=structuredClone(command.items);s.step=2;return s;
 }
 if(s.step<2)throw new Error('请先由设计发布方案、项目经理提交采购清单。');
 const next=advance(s.step,role,purchaseSteps,blocked);
 if(s.step===3){
  if(!command.ordered||command.ordered.length!==s.items.length||!requiredText(command.supplier??'',200))throw new Error('请填写供应商和每种物品的下单数量、约定到货日期。');
  command.ordered.forEach(x=>{quantityUnits(x.quantity);if(!validDemoDate(x.eta))throw new Error('请填写有效约定到货日期。');});
  if(command.ordered.some((x,i)=>quantityUnits(x.quantity)!==quantityUnits(s.items[i].quantity))&&!command.difference?.trim())throw new Error('订购数量有差异，请填写说明供项目经理复核。');
  s.ordered=structuredClone(command.ordered);s.supplier=command.supplier!.trim();s.difference=command.difference??'';
 }
 if([4,5,6,7].includes(s.step)&&!command.confirmed)throw new Error('请先明确勾选本节点的核对项。');
 if(s.step===5)s.arrivals=structuredClone(s.ordered);
 if(s.step===6&&(!s.arrivals.length||s.arrivals.length!==s.items.length))throw new Error('实际到货登记未齐，不能确认质量合格。');
 if(s.step===7){
  if(!requiredText(command.contract??'',120)||!/^\d{1,9}(\.\d{1,2})?$/.test(command.amount??'')||Number(command.amount)<=0)throw new Error('请填写合成合同编号及大于0的金额，最多两位小数。');
  s.contract=command.contract!.trim();s.amount=command.amount!;s.archives.push({title:s.demand.title,items:structuredClone(s.items),contract:s.contract});
 }
 s.step=next;return s;
}
export function parseDemoItemsCsv(text:string):DemoItem[]{
 const rows:string[][]=[];let row:string[]=[],value='',quoted=false;
 for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){value+='"';i++;}else quoted=!quoted;}else if(!quoted&&(c===','||c==='\n')){row.push(value.trim());value='';if(c==='\n'){if(row.some(Boolean))rows.push(row);row=[];}}else if(c!=='\r'||quoted)value+=c;}
 if(quoted)throw new Error('CSV引号未闭合。');row.push(value.trim());if(row.some(Boolean))rows.push(row);
 const header=rows.shift()?.map(x=>x.replace(/^\ufeff/,''));if(header?.join(',')!=='物料,规格,数量,单位,需用日期')throw new Error('CSV表头应为物料、规格、数量、单位、需用日期。');
 const items=rows.map((r,i)=>{if(r.length!==5||r.some(x=>/^[=+@]/.test(x)))throw new Error('CSV源行'+(i+2)+'列数不符或包含公式。');return {material:r[0],spec:r[1],quantity:r[2],unit:r[3],need_by:r[4]};});validateDemoItems(items);return items;
}
export type DemoCase={input:string;expected:string};
export function evaluateDemoRule(definition:RuleDefinition,cases:DemoCase[]){
 if(!cases.length||cases.length>20)throw new Error('请提供1—20条固定用例。');
 const results=cases.map(c=>{if(!c.input.trim()||!c.expected.trim())throw new Error('测试输入和预期都不能为空。');try{const actual=runRule(definition,c.input).output;return {...c,actual,passed:actual===c.expected,error:''};}catch(e){return {...c,actual:'',passed:false,error:e instanceof Error?e.message:'规则失败'};}});
 return {signature:JSON.stringify({definition,cases}),passed:results.every(x=>x.passed),results};
}
export function mayPublishDemo(report:ReturnType<typeof evaluateDemoRule>|null,definition:RuleDefinition,cases:DemoCase[]){return !!report&&report.passed&&report.signature===JSON.stringify({definition,cases});}
