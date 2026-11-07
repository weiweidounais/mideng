import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../src/pilot/rule-results.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {canPublishEvaluation}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
const cases=[{input:' 材料 ',expectContains:' 核对 ',expectStatus:'success'}],app={id:'a',revision:3};
const report={application_id:'a',application_revision:3,passed:1,total:1,cases:[{input:'材料',expectContains:'核对',expectStatus:'success',passed:true}]};
test('matching application draft and normalized cases may be confirmed',()=>assert.equal(canPublishEvaluation(report,app,cases),true));
test('editing draft, expectation, input or application invalidates old evaluation',()=>{
 assert.equal(canPublishEvaluation(report,{...app,revision:4},cases),false);assert.equal(canPublishEvaluation(report,{...app,id:'other'},cases),false);
 for(const row of [{...cases[0],input:'其他输入'},{...cases[0],expectContains:'其他预期'},{...cases[0],expectStatus:'failed'}])assert.equal(canPublishEvaluation(report,app,[row]),false);
});
test('missing partial failed and empty reports cannot authorize publication',()=>{
 for(const value of [null,{...report,total:0,passed:0},{...report,passed:0},{...report,cases:[]},{...report,cases:[{...report.cases[0],passed:false}]}])assert.equal(canPublishEvaluation(value,app,cases),false);
});
