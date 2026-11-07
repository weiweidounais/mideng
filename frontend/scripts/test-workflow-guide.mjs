import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../src/pilot/workflow-guide.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {canCreateRequirement,requirementNextStep}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
test('business creation accepts project administrator and retains ordinary role limits',()=>{
 for(const roles of [[],['项目经理'],['采购','质量','财务']])assert.equal(canCreateRequirement(roles),false);
 for(const roles of [['市场'],['商务'],['管理员'],['管理员','商务']])assert.equal(canCreateRequirement(roles),true);
});
const formal={has_draft:false,versions:[{current:true}]};
test('draft and withdrawn requirement cannot be presented as ready for design or procurement',()=>{
 assert.equal(requirementNextStep({has_draft:true,versions:[]},[]),'publish-requirement');
 assert.equal(requirementNextStep({has_draft:false,versions:[{current:false}]},[formal]),'review-requirement');
});
test('next step respects scheme draft, review and actual current formal source',()=>{
 assert.equal(requirementNextStep(formal,[]),'create-scheme');
 assert.equal(requirementNextStep(formal,[{has_draft:true,versions:[]}]),'publish-scheme');
 assert.equal(requirementNextStep(formal,[{has_draft:true,needs_review:true,versions:[{current:false}]}]),'review-scheme');
 assert.equal(requirementNextStep(formal,[formal]),'procurement');
 assert.equal(requirementNextStep(formal,[{has_draft:false,versions:[{current:false}]}]),'create-scheme');
});


const permissionSource=await readFile(new URL('../src/pilot/business-permissions.ts',import.meta.url),'utf8');
const permissionJs=ts.transpileModule(permissionSource,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {businessRoles,hasBusinessRole,canActFor}=await import('data:text/javascript;base64,'+Buffer.from(permissionJs).toString('base64'));
test('project administrator supports every known business role without changing assigned roles',()=>{
 const roles=['管理员'];for(const role of ['市场','商务','设计','项目经理','采购','质量','工厂','现场','财务'])assert.equal(hasBusinessRole(roles,role),true);
 assert.deepEqual(roles,['管理员']);assert.equal(hasBusinessRole(roles,'unknown'),false);
 assert.deepEqual(businessRoles(['采购']),['采购']);assert.equal(hasBusinessRole(['采购'],'财务'),false);
});
test('admin takeover uses actual actor while ordinary account still requires assignment',()=>{
 assert.equal(canActFor(['管理员'],'admin','purchase'),true);
 assert.equal(canActFor(['采购'],'other','purchase'),false);
 assert.equal(canActFor(['采购'],'purchase','purchase'),true);
});
