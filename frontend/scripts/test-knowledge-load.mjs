import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../src/pilot/knowledge-load.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {readKnowledgeSnapshot}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
test('a removed library never triggers document or application reads',async()=>{
 const calls=[];const result=await readKnowledgeSnapshot(async path=>{calls.push(path);return [{id:'allowed'}];},'/projects/p/knowledge','revoked');
 assert.equal(result.accessible,false);assert.deepEqual(result.documents,[]);assert.deepEqual(result.applications,[]);assert.equal(calls.length,1);
});
test('independent documents and applications are read together before commit',async()=>{
 const calls=[];let finishDocuments;const documentPromise=new Promise(resolve=>{finishDocuments=resolve;});
 const pending=readKnowledgeSnapshot(async path=>{calls.push(path);if(path.endsWith('/libraries'))return [{id:'l'}];if(path.endsWith('/documents'))return documentPromise;return [{id:'app'}];},'/projects/p/knowledge','l');
 await new Promise(resolve=>setImmediate(resolve));assert.equal(calls.length,3);finishDocuments({items:[{id:'doc'}]});
 const result=await pending;assert.equal(result.documents[0].id,'doc');assert.equal(result.applications[0].id,'app');assert.equal(result.accessible,true);
});
test('a partial response failure cannot replace a previously verified snapshot',async()=>{
 const original={libraries:[{id:'l'}],documents:[{id:'verified'}],applications:[],accessible:true};let displayed=original;
 await assert.rejects(async()=>{displayed=await readKnowledgeSnapshot(async path=>{if(path.endsWith('/libraries'))return [{id:'l'}];if(path.endsWith('/documents'))return {items:[{id:'uncommitted'}]};throw new Error('temporary read failure');},'/projects/p/knowledge','l');});
 assert.equal(displayed,original);
});
test('one abort signal is passed to every scoped read',async()=>{
 const abort=new AbortController();const signals=[];
 await readKnowledgeSnapshot(async(path,init)=>{signals.push(init.signal);return path.endsWith('/libraries')?[{id:'l'}]:path.endsWith('/documents')?{items:[]}:[];},'/projects/p/knowledge','l',abort.signal);
 assert.equal(signals.length,3);assert.ok(signals.every(signal=>signal===abort.signal));
});
