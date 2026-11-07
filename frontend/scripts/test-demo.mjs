import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../src/demo/model.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {advance,purchaseSteps,traceSteps,initialRule,runRule,initialBusiness,transitionBusiness,parseDemoItemsCsv,evaluateDemoRule,mayPublishDemo}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
test('demo procurement preserves PM review arrival quality and commerce ordering',()=>{assert.deepEqual(purchaseSteps.map(x=>x.role),['设计','项目经理','采购','采购','项目经理','采购','质量','商务']);let step=0;for(const item of purchaseSteps)step=advance(step,item.role,purchaseSteps);assert.equal(step,purchaseSteps.length);assert.throws(()=>advance(step,'商务',purchaseSteps));});
test('demo source and selected role guards block advancement',()=>{assert.throws(()=>advance(0,'采购',purchaseSteps));assert.throws(()=>advance(0,'设计',purchaseSteps,true));assert.equal(advance(0,'设计',purchaseSteps),1);});
test('trace demo retains distinct inspection pressure and completion confirmations',()=>{assert.equal(traceSteps[3].role,'质量');assert.equal(traceSteps[7].role,'质量');assert.equal(traceSteps[8].title,'质量确认完成');});
test('rules return a local template result and published clones remain separate',()=>{const draft=structuredClone(initialRule),published=structuredClone(draft);draft.nodes[1].config.template='新版：{{input}}';assert.equal(runRule(draft,'到货').output,'新版：到货');assert.ok(!runRule(published,'到货').output.includes('新版'));});
test('cyclic and unknown edges fail rather than evaluate arbitrary code',()=>{const d=structuredClone(initialRule);d.edges.push({id:'back',source:'text',target:'start'});assert.throws(()=>runRule(d,'示例'));const other=structuredClone(initialRule);other.edges[0].target='missing';assert.throws(()=>runRule(other,'示例'));assert.throws(()=>runRule(initialRule,''));});
test('condition branches select a single route',()=>{const d={name:'规则',nodes:[{id:'start',kind:'start',config:{}},{id:'gate',kind:'condition',config:{source:'{{input}}',operator:'contains',value:'到货'}},{id:'yes',kind:'template',config:{template:'质量验收'}},{id:'no',kind:'template',config:{template:'继续核对'}},{id:'out',kind:'output',config:{template:'{{previous.output}}'}}],edges:[{id:'s-g',source:'start',target:'gate'},{id:'g-y',source:'gate',target:'yes',sourceHandle:'true'},{id:'g-n',source:'gate',target:'no',sourceHandle:'false'},{id:'y-o',source:'yes',target:'out'},{id:'n-o',source:'no',target:'out'}]};assert.equal(runRule(d,'已到货').output,'质量验收');assert.equal(runRule(d,'未下单').output,'继续核对');});
test('public entry disallows backend connections and imports no account transport',async()=>{const html=await readFile(new URL('../demo.html',import.meta.url),'utf8');assert.ok(html.includes("connect-src 'none'"));const app=await readFile(new URL('../src/demo/DemoApp.tsx',import.meta.url),'utf8');assert.ok(!/from ['"][^'"]*(?:client|api|store)['"]/.test(app));assert.ok(!/\b(?:fetch|XMLHttpRequest|WebSocket)\s*\(/.test(app));assert.ok(app.includes('公开演示'));});
const importSource=await readFile(new URL('../src/demo/temporary-import.ts',import.meta.url),'utf8');
const importJs=ts.transpileModule(importSource,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {readTemporaryDocument,addTemporaryDocument,temporaryImportLimits}=await import('data:text/javascript;base64,'+Buffer.from(importJs).toString('base64'));
test('temporary UTF-8 imports preserve the exact original bytes and plain text',async()=>{
 const file=new File(['\ufeff# 合成记录\r\n本地导入验证 <script>example()</script>\r\n'],'合成记录.md',{type:'text/markdown'});
 const doc=await readTemporaryDocument(file);
 assert.equal(doc.kind,'temporary');assert.equal(doc.title,file.name);assert.equal(doc.original,file);assert.ok(doc.text.includes('<script>example()</script>'));
 assert.deepEqual(new Uint8Array(await doc.original.arrayBuffer()),new Uint8Array(await file.arrayBuffer()));
 assert.equal(doc.fingerprint.length,64);assert.equal(addTemporaryDocument([],doc)[0],doc);
 assert.equal((await readTemporaryDocument(new File(['MZ 合成纯文本说明'],'说明.txt'))).text,'MZ 合成纯文本说明');
});
test('BOM-marked UTF-16 text is readable while unknown encodings fail explicitly',async()=>{
 const bytes=new Uint8Array([255,254,...Buffer.from('合成到货\r\n','utf16le')]);
 const doc=await readTemporaryDocument(new File([bytes],'中文.txt'));assert.equal(doc.text,'合成到货\r\n');
 const bigEndian=new Uint8Array([254,255,0x54,0x08,0x62,0x10]);assert.equal((await readTemporaryDocument(new File([bigEndian],'中文.txt'))).text,'合成');
 await assert.rejects(()=>readTemporaryDocument(new File([new Uint8Array([0xff,0x61])],'错误编码.txt')),/UTF-8/);
});
test('unsupported, disguised binary, blank and oversized imports are rejected',async()=>{
 for(const [file,pattern] of [
  [new File(['hello'],'资料.pdf'),/目前支持/],
  [new File(['%PDF-1.7'],'伪装.txt'),/文件内容不是/],
  [new File([new Uint8Array([80,75,3,4,1,2])],'伪装.md'),/文件内容不是/],
  [new File(['abc\u0000abc'],'二进制.csv'),/控制字符/],
  [new File([''],'空白.txt'),/文件是空的/],
  [new File([' \r\n '],'空格.txt'),/没有可检索/],
  [new File([new Uint8Array(temporaryImportLimits.fileBytes+1)],'超大.txt'),/1 MB/],
 ])await assert.rejects(()=>readTemporaryDocument(file),pattern);
 await assert.rejects(()=>readTemporaryDocument({name:'无法读取.txt',size:4,arrayBuffer:async()=>{throw new Error('unreadable');}}),/读取失败/);
});
test('duplicates and capacity limits preserve current files and distinct originals',async()=>{
 const first=await readTemporaryDocument(new File(['相同文本'],'原文.txt'));
 const duplicate=await readTemporaryDocument(new File(['相同文本'],'原文.txt'));
 assert.throws(()=>addTemporaryDocument([first],duplicate),/已导入/);
 const changed=await readTemporaryDocument(new File(['另一版文本'],'原文.txt'));assert.equal(addTemporaryDocument([first],changed).length,2);
 const renamed=await readTemporaryDocument(new File(['相同文本'],'另一来源.txt'));assert.equal(addTemporaryDocument([first],renamed).length,2);
 const ten=Array.from({length:10},(_,i)=>({...first,title:'来源'+i}));assert.throws(()=>addTemporaryDocument(ten,renamed),/10/);assert.equal(ten.length,10);
 const huge=await readTemporaryDocument(new File(['x'.repeat(temporaryImportLimits.fileBytes)],'大文本.txt'));
 const five=Array.from({length:5},(_,i)=>({...huge,title:'来源'+i}));assert.throws(()=>addTemporaryDocument(five,renamed),/5 MB/);assert.equal(five.length,5);
});
test('temporary import stays in memory, renders plain text, and uses no network transport',async()=>{
 for(const name of ['DemoApp.tsx','KnowledgeExplorer.tsx','BusinessWorkflow.tsx','model.ts','temporary-import.ts']){
  const code=await readFile(new URL('../src/demo/'+name,import.meta.url),'utf8');
  assert.ok(!/\b(?:fetch|XMLHttpRequest|WebSocket|sendBeacon)\s*\(/.test(code),name);
  assert.ok(!/\b(?:localStorage|sessionStorage|indexedDB|dangerouslySetInnerHTML)\b/.test(code),name);
 }
});

const demoItems=[{material:'PM管材',spec:'DN25',quantity:'2.75',unit:'米',need_by:'2026-12-15'},{material:'PM接头',spec:'DN25螺纹',quantity:'5',unit:'个',need_by:'2026-12-15'}];
const schemeOnly=s=>transitionBusiness(s,'设计',{kind:'scheme',data:{title:'落地方案',notes:'实施路径和工序，采购物品由PM核定',risks:''}});
test('public demand starts in market or commerce and design does not author procurement items',()=>{
 let s=transitionBusiness(initialBusiness(),'市场',{kind:'demand',data:{title:'新需求',summary:'合成内容',source:'合成来源'}});
 assert.equal(s.demandPublished,false);assert.throws(()=>schemeOnly(s));assert.throws(()=>transitionBusiness(s,'市场',{kind:'publish-demand'}));
 s=transitionBusiness(s,'商务',{kind:'publish-demand'});s=schemeOnly(s);assert.equal(s.step,1);assert.deepEqual(s.items,[]);
 assert.throws(()=>transitionBusiness(s,'设计',{kind:'request',items:demoItems}));
 const pm=transitionBusiness(s,'项目经理',{kind:'request',items:demoItems});assert.deepEqual(pm.items,demoItems);assert.equal(s.items.length,0);
 const inputs=structuredClone(demoItems);const frozen=transitionBusiness(s,'项目经理',{kind:'request',items:inputs});inputs[0].quantity='99';assert.equal(frozen.items[0].quantity,'2.75');
});
test('administrator public flow keeps state order, PM quantities, arrival, quality and archive gates',()=>{
 let s=transitionBusiness(initialBusiness(),'管理员',{kind:'scheme',data:{title:'合成方案',notes:'可落地的实施方案',risks:''}});
 s=transitionBusiness(s,'管理员',{kind:'request',items:demoItems});s=transitionBusiness(s,'管理员',{kind:'next'});
 assert.throws(()=>transitionBusiness(s,'管理员',{kind:'next'}));
 s=transitionBusiness(s,'管理员',{kind:'next',supplier:'合成供应商',ordered:demoItems.map(x=>({quantity:x.quantity,eta:x.need_by}))});
 assert.throws(()=>transitionBusiness(s,'管理员',{kind:'next'}));
 for(let i=0;i<3;i++)s=transitionBusiness(s,'管理员',{kind:'next',confirmed:true});
 assert.equal(s.step,7);assert.deepEqual(s.arrivals.map(x=>x.quantity),['2.75','5']);
 assert.throws(()=>transitionBusiness(s,'管理员',{kind:'next',confirmed:true}));
 s=transitionBusiness(s,'管理员',{kind:'next',confirmed:true,contract:'SYN-001',amount:'1.00'});assert.equal(s.step,8);assert.equal(s.archives.length,1);
 assert.throws(()=>transitionBusiness(s,'管理员',{kind:'next',confirmed:true}));
});
test('public PM items reject missing, zero, excessive precision and invalid dates without falling back to design',()=>{
 const s=schemeOnly(initialBusiness());
 for(const items of [[],[{...demoItems[0],quantity:'0'}],[{...demoItems[0],quantity:'1.1234567'}],[{...demoItems[0],need_by:'2026-02-30'}]])assert.throws(()=>transitionBusiness(s,'项目经理',{kind:'request',items}));
 assert.throws(()=>transitionBusiness(s,'项目经理',{kind:'request',items:demoItems},true));assert.equal(s.step,1);
});
test('purchase CSV precheck supports quoted cells and rejects malformed or formula data',()=>{
 const csv='物料,规格,数量,单位,需用日期\nPM管材,"DN25,镀锌",2.75,米,2026-12-15\n';const rows=parseDemoItemsCsv(csv);assert.equal(rows[0].spec,'DN25,镀锌');
 for(const bad of ['物料,规格\nX,Y','物料,规格,数量,单位,需用日期\n=SCRIPT(),DN25,1,米,2026-12-15','物料,规格,数量,单位,需用日期\nX,DN25,0,米,2026-12-15'])assert.throws(()=>parseDemoItemsCsv(bad));
});
test('rule publication requires matching passing cases and preserves failures for review',()=>{
 const cases=[{input:'到货',expected:'处理建议：到货。请由项目责任人核对。'}];const report=evaluateDemoRule(initialRule,cases);assert.equal(mayPublishDemo(report,initialRule,cases),true);
 const fail=evaluateDemoRule(initialRule,[{input:'到货',expected:'不一致'}]);assert.equal(fail.passed,false);assert.ok(fail.results[0].actual);assert.equal(mayPublishDemo(fail,initialRule,[{input:'到货',expected:'不一致'}]),false);
 const changed=structuredClone(initialRule);changed.nodes[1].config.template='新内容';assert.equal(mayPublishDemo(report,changed,cases),false);assert.equal(mayPublishDemo(report,initialRule,[{input:'别的输入',expected:'不同预期'}]),false);
});
