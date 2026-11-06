import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
import {readFile} from 'node:fs/promises';
const src=await readFile(new URL('../src/pilot/navigation.ts',import.meta.url),'utf8');
const js=ts.transpileModule(src,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {parseRoute,routeSearch,linkRoute,mutationRoute}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
test('authorized source links round trip project object kind and frozen version',()=>{const l={project_id:'p1',section:'procurement',object_id:'po-1',version_id:'v2',kind:'procurement'};const r=parseRoute(routeSearch(linkRoute(l)));assert.equal(r.project,'p1');assert.equal(r.object,'po-1');assert.equal(r.version,'v2');assert.equal(r.kind,'procurement')});
test('invalid, repeated, unknown and incomplete location parameters are refused',()=>{for(const q of ['?project=p&project=q','?token=secret','?object=x','?project=p&version=x','?project=p&section=unknown','?project=p&section=toString','?project=p&section=constructor','?page=0','?page=1.5','?project=../secret','?project=p&object=o&kind=unknown'])assert.ok(parseRoute(q).error,q)});
test('legacy spool labels retain optional project until server validation',()=>{const r=parseRoute('?project=p&spool=s');assert.equal(r.spool,'s');assert.equal(r.project,'p');assert.ok(parseRoute('?spool=s&object=o').error)});
test('browser pagination and history filters round trip independently',()=>{const r=parseRoute(routeSearch({view:'workbench',mode:'all',page:3}));assert.equal(r.page,3);assert.equal(r.mode,'all');assert.equal(parseRoute('?view=projects').view,'projects')});

test('trace search keeps authorized project and refuses unrelated query scopes',()=>{const r=parseRoute(routeSearch({project:'p',section:'trace',q:'SP-1',page:2}));assert.equal(r.q,'SP-1');assert.equal(r.page,2);for(const q of ['?q=SP-1','?project=p&section=cost&q=SP-1','?project=p&section=trace&q=%25'])assert.ok(parseRoute(q).error)});

test('resolved assurance requests return to the owning exception or export section',()=>{
 for(const path of ['/projects/p/assurance/exceptions/e/actions','/projects/p/assurance/exceptions/e/files']){const r=mutationRoute({path,resultId:'file-or-result-id'});assert.equal(r.section,'assurance');assert.equal(r.object,'e');assert.equal(r.kind,'assurance');assert.ok(!parseRoute(routeSearch(r)).error);}
 const r=mutationRoute({path:'/projects/p/assurance/exports',resultId:'export-id'});assert.equal(r.section,'assurance');assert.equal(r.object,undefined);assert.ok(!parseRoute(routeSearch(r)).error);
});
test('upload result links retain business owners across trace procurement and change routes',()=>{for(const [path,section,kind,id] of [['/projects/p/trace/spools/s/files','trace','spool','s'],['/projects/p/procurement/orders/o/files','procurement','procurement','o'],['/projects/p/changes/c/files','changes','change','c']]){const r=mutationRoute({path,resultId:'uploaded-file'});assert.equal(r.section,section);assert.equal(r.kind,kind);assert.equal(r.object,id);}});
