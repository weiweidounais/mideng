import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
import {readFile} from 'node:fs/promises';
const src=await readFile(new URL('../src/pilot/navigation.ts',import.meta.url),'utf8');
const js=ts.transpileModule(src,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {parseRoute,routeSearch,linkRoute,mutationRoute,pickWorkspaceProject}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
test('home and feature navigation share an explicitly selected accessible project',()=>{
 const projects=[{id:'a'},{id:'b'}];assert.equal(pickWorkspaceProject(projects,undefined,'b'),projects[1]);assert.equal(pickWorkspaceProject(projects,'a','b'),projects[0]);assert.equal(pickWorkspaceProject(projects,undefined,undefined),projects[0]);
});
test('revoked project preferences never produce an inaccessible navigation target',()=>{
 const accessible=[{id:'allowed'}];assert.equal(pickWorkspaceProject(accessible,'revoked','revoked'),accessible[0]);assert.equal(pickWorkspaceProject([],'revoked','revoked'),undefined);
});
test('project context cannot carry another account project into a fresh accessible list',()=>{
 const currentAccount=[{id:'new-account-project'}];assert.equal(pickWorkspaceProject(currentAccount,undefined,'previous-account-project'),currentAccount[0]);
});
test('authorized source links round trip project object kind and frozen version',()=>{const l={project_id:'p1',section:'procurement',object_id:'po-1',version_id:'v2',kind:'procurement'};const r=parseRoute(routeSearch(linkRoute(l)));assert.equal(r.project,'p1');assert.equal(r.object,'po-1');assert.equal(r.version,'v2');assert.equal(r.kind,'procurement')});
test('invalid, repeated, unknown and incomplete location parameters are refused',()=>{for(const q of ['?project=p&project=q','?token=secret','?object=x','?project=p&version=x','?project=p&section=unknown','?project=p&section=toString','?project=p&section=constructor','?page=0','?page=1.5','?project=../secret','?project=p&object=o&kind=unknown'])assert.ok(parseRoute(q).error,q)});
test('legacy spool labels retain optional project until server validation',()=>{const r=parseRoute('?project=p&spool=s');assert.equal(r.spool,'s');assert.equal(r.project,'p');assert.ok(parseRoute('?spool=s&object=o').error)});
test('browser pagination and history filters round trip independently',()=>{const r=parseRoute(routeSearch({view:'workbench',mode:'all',page:3}));assert.equal(r.page,3);assert.equal(r.mode,'all');assert.equal(parseRoute('?view=projects').view,'projects')});

test('application deep links preserve project space and tab across reload and history',()=>{
 for(const tab of ['documents','applications']){const route=parseRoute(routeSearch({project:'p',section:'knowledge',kind:'library',object:'l',tab}));assert.equal(route.tab,tab);assert.equal(route.object,'l');assert.equal(route.kind,'library');assert.ok(!route.error);}
 assert.equal(parseRoute(routeSearch({project:'p',section:'knowledge',tab:'applications'})).tab,'applications');
 assert.equal(parseRoute('?project=p&section=knowledge&object=l&kind=library').tab,undefined);
});
test('application tabs cannot be injected into unrelated or incomplete business locations',()=>{
 for(const query of ['?tab=applications','?project=p&tab=applications','?project=p&section=changes&tab=applications','?project=p&section=knowledge&tab=unknown','?project=p&section=knowledge&tab=applications&tab=documents','?project=p&section=knowledge&panel=members&tab=applications','?spool=s&tab=applications'])assert.ok(parseRoute(query).error,query);
});

test('new requirement entry is a refreshable project-scoped action with no existing object',()=>{
 const route=parseRoute(routeSearch({project:'p',section:'requirements',action:'new-requirement'}));assert.equal(route.action,'new-requirement');assert.equal(route.project,'p');assert.ok(!route.error);
});
test('creation action rejects cross-section, object, member and repeated action parameters',()=>{
 for(const query of ['?action=new-requirement','?project=p&section=changes&action=new-requirement','?project=p&section=requirements&action=other','?project=p&section=requirements&action=new-requirement&object=x&kind=document','?project=p&section=requirements&action=new-requirement&panel=members','?project=p&section=requirements&action=new-requirement&action=new-requirement'])assert.ok(parseRoute(query).error,query);
});

test('members entry round trips while refusing unrelated or incomplete scopes',()=>{
 const route=parseRoute(routeSearch({project:'p',section:'requirements',panel:'members'}));assert.equal(route.panel,'members');assert.equal(route.project,'p');assert.ok(!route.error);
 for(const query of ['?panel=members','?project=p&panel=other','?project=p&section=cost&panel=members','?project=p&object=x&panel=members','?project=p&panel=members&spool=s'])assert.ok(parseRoute(query).error,query);
});

test('trace search keeps authorized project and refuses unrelated query scopes',()=>{const r=parseRoute(routeSearch({project:'p',section:'trace',q:'SP-1',page:2}));assert.equal(r.q,'SP-1');assert.equal(r.page,2);for(const q of ['?q=SP-1','?project=p&section=cost&q=SP-1','?project=p&section=trace&q=%25'])assert.ok(parseRoute(q).error)});

test('resolved assurance requests return to the owning exception or export section',()=>{
 for(const path of ['/projects/p/assurance/exceptions/e/actions','/projects/p/assurance/exceptions/e/files']){const r=mutationRoute({path,resultId:'file-or-result-id'});assert.equal(r.section,'assurance');assert.equal(r.object,'e');assert.equal(r.kind,'assurance');assert.ok(!parseRoute(routeSearch(r)).error);}
 const r=mutationRoute({path:'/projects/p/assurance/exports',resultId:'export-id'});assert.equal(r.section,'assurance');assert.equal(r.object,undefined);assert.ok(!parseRoute(routeSearch(r)).error);
});
test('upload result links retain business owners across trace procurement and change routes',()=>{for(const [path,section,kind,id] of [['/projects/p/trace/spools/s/files','trace','spool','s'],['/projects/p/procurement/orders/o/files','procurement','procurement','o'],['/projects/p/changes/c/files','changes','change','c']]){const r=mutationRoute({path,resultId:'uploaded-file'});assert.equal(r.section,section);assert.equal(r.kind,kind);assert.equal(r.object,id);}});


test('market and commerce desks retain project and document across deep links',()=>{
 for(const desk of ['market','commerce']){
  const entry=parseRoute(routeSearch({project:'p',section:'requirements',desk}));assert.equal(entry.desk,desk);assert.ok(!entry.error);
  const doc=parseRoute(routeSearch({project:'p',section:'requirements',desk,object:'req',kind:'document'}));assert.equal(doc.desk,desk);assert.equal(doc.object,'req');assert.ok(!doc.error);
  const action=parseRoute(routeSearch({project:'p',section:'requirements',desk,action:'new-requirement'}));assert.equal(action.desk,desk);assert.equal(action.action,'new-requirement');assert.ok(!action.error);
 }
});
test('business desks cannot cross into procurement knowledge members or unknown scopes',()=>{
 for(const query of ['?desk=market','?project=p&section=procurement&desk=commerce','?project=p&section=knowledge&desk=market','?project=p&section=requirements&desk=constructor','?project=p&section=requirements&desk=market&desk=commerce','?project=p&section=requirements&desk=commerce&panel=members','?project=p&section=requirements&desk=market&object=po&kind=procurement'])assert.ok(parseRoute(query).error,query);
});
