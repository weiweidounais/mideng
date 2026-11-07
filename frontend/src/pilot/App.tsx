import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Modal, Select, Drawer } from 'antd';
import Workbench from './Workbench';
import {parseRoute,routeSearch,sections,businessDesks,pickWorkspaceProject,type ViewRoute,type ObjectLink} from './navigation';
import Auth from './Auth';
import {RequestRecovery} from './FormSupport';
import Handoff from './Handoff';
import KnowledgeFlow from './KnowledgeFlow';
import { ApiError, request, mutate, setSession, localDate, type Account, type Audit, type Member, type Project, type Session } from './client';
const ROLES = ['市场', '商务', '设计', '采购', '项目经理', '工厂', '现场', '质量', '财务', '管理员'];
const actionName: Record<string, string> = { 'project.create': '创建项目', 'project.edit': '修改项目', 'member.update': '配置成员' };
function formValues(e: FormEvent<HTMLFormElement>) { e.preventDefault(); return new FormData(e.currentTarget); }
export default function App() {
    const [ready, setReady] = useState(false), [setup, setSetup] = useState(false), [session, setCurrent] = useState<Session | null>(null);
    const [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
    const [workspaceProjectId,setWorkspaceProjectId]=useState('');
    const [projects, setProjects] = useState<Project[]>([]), [selected, setSelected] = useState<Project | null>(null), [members, setMembers] = useState<Member[]>([]), [audit, setAudit] = useState<Audit[]>([]), [accounts, setAccounts] = useState<Account[]>([]);
    const [dialog, setDialog] = useState<'project' | 'account' | 'member' | 'rename' | null>(null), [member, setMember] = useState<Member | null>(null), [roles, setRoles] = useState<string[]>([]), [accountId, setAccountId] = useState('');
    const [draftName, setDraftName] = useState(''), [conflictRevision, setConflictRevision] = useState<number | null>(null);
    const [route,setRoute]=useState<ViewRoute>(()=>parseRoute(window.location.search));
    const [link,setLink]=useState<ObjectLink|null>(null),[reading,setReading]=useState(false),[readError,setReadError]=useState(''),[reload,setReload]=useState(0),[homeLoading,setHomeLoading]=useState(true),[drawer,setDrawer]=useState(false);
    const workspaceProject=pickWorkspaceProject(projects,route.project,workspaceProjectId);
    const routeRef=useRef(route);routeRef.current=route;
    function navigate(next:ViewRoute,replace=false){if(!window.dispatchEvent(new Event('mideng-before-navigate',{cancelable:true})))return false;const search=routeSearch(next);if(window.location.search!==search)window.history[replace?'replaceState':'pushState']({},'',window.location.pathname+search);setRoute(parseRoute(search));if(next.project)setWorkspaceProjectId(next.project);setDrawer(false);setReadError('');return true;}
    useEffect(()=>{const pop=()=>{if(!window.dispatchEvent(new Event('mideng-before-navigate',{cancelable:true}))){window.history.pushState({},'',window.location.pathname+routeSearch(routeRef.current));return;}setRoute(parseRoute(window.location.search));setDrawer(false);};const expired=()=>{setWorkspaceProjectId('');setCurrent(null);setProjects([]);setSelected(null);setMembers([]);setAudit([]);setAccounts([]);setLink(null);setReading(false);setError('会话已失效，请重新登录以恢复原查看位置。');};window.addEventListener('popstate',pop);window.addEventListener('mideng-session-expired',expired);return()=>{window.removeEventListener('popstate',pop);window.removeEventListener('mideng-session-expired',expired);};},[]);
    const pending = useRef(new Map<string, string>());
    const loadSequence = useRef(0);
    function signedIn(s: Session) { setWorkspaceProjectId('');setSession(s); setCurrent(s); setError(''); setSelected(null); }
    useEffect(() => { let cancelled = false; (async () => { try {
        const state = await request<{
            required: boolean;
        }>('/setup');
        if (cancelled)
            return;
        setSetup(state.required);
        if (!state.required) {
            try {
                const s = await request<Session>('/session');
                if (!cancelled)
                    signedIn(s);
            }
            catch (e) {
                if (!(e instanceof ApiError) || e.status !== 401)
                    throw e;
            }
        }
    }
    catch (e) {
        if (!cancelled)
            setError(String(e));
    }
    finally {
        if (!cancelled)
            setReady(true);
    } })(); return () => { cancelled = true; }; }, []);
    async function refresh(){const [ps,as]=await Promise.all([request<Project[]>('/projects'),session?.account.is_admin?request<Account[]>('/accounts'):Promise.resolve([])]);setProjects(ps);setAccounts(as);return ps;}
    useEffect(()=>{if(!session)return;const controller=new AbortController();setHomeLoading(true);Promise.all([request<Project[]>('/projects',{signal:controller.signal}),session.account.is_admin?request<Account[]>('/accounts',{signal:controller.signal}):Promise.resolve([])]).then(([ps,as])=>{if(!controller.signal.aborted){setProjects(ps);setAccounts(as);}}).catch(e=>{if(!controller.signal.aborted)setError(e.message);}).finally(()=>{if(!controller.signal.aborted)setHomeLoading(false);});return()=>controller.abort();},[session]);
    async function openProject(p:Project){if(route.project===p.id)setReload(x=>x+1);else navigate({project:p.id,section:'requirements'});}
    useEffect(()=>{
        if(!session)return;const controller=new AbortController();const seq=++loadSequence.current;setSelected(null);setMembers([]);setAudit([]);setLink(null);setReadError('');setReading(!!(route.project||route.spool));
        if(route.error||(!route.project&&!route.spool)){setReading(false);return()=>controller.abort();}
        (async()=>{try{
            if(route.spool){const p=await request<Project>('/spool-locator/'+encodeURIComponent(route.spool),{signal:controller.signal});if(route.project&&route.project!==p.id)throw new Error('二维码与地址项目不一致，请从原标签重新打开。');if(!controller.signal.aborted)navigate({project:p.id,section:'trace',object:route.spool,kind:'spool'},true);return;}
            const pid=route.project!;const query=new URLSearchParams({section:route.section??'requirements'});if(route.object)query.set('object_id',route.object);if(route.version)query.set('version_id',route.version);if(route.kind)query.set('kind',route.kind);
            const [p,ms,location]=await Promise.all([request<Project>('/projects/'+pid,{signal:controller.signal}),request<Member[]>('/projects/'+pid+'/members',{signal:controller.signal}),request<ObjectLink>('/projects/'+pid+'/workspace/locate?'+query,{signal:controller.signal})]);
            if(controller.signal.aborted||seq!==loadSequence.current)return;setSelected(p);setWorkspaceProjectId(p.id);setMembers(ms);setLink(location);
            if(p.actions.includes('audit.read'))request<Audit[]>('/projects/'+pid+'/audit',{signal:controller.signal}).then(xs=>{if(!controller.signal.aborted&&seq===loadSequence.current)setAudit(xs);}).catch(e=>{if(!controller.signal.aborted)setError(e.message);});
        }catch(e){if(!controller.signal.aborted&&seq===loadSequence.current){setReadError(e instanceof Error?e.message:'位置不可访问，请返回本人工作台。');setSelected(null);}}finally{if(!controller.signal.aborted&&seq===loadSequence.current)setReading(false);}})();
        return()=>controller.abort();
    },[session,route,reload]);
    async function save<T>(path: string, method: string, body: unknown): Promise<T> { const signature = method + path + JSON.stringify(body); const key = pending.current.get(signature) ?? crypto.randomUUID(); pending.current.set(signature, key); const result = await mutate<T>(path, method, body, key); pending.current.delete(signature); return result; }
    async function operation(work: () => Promise<void>) { if (busy)
        return; setBusy(true); setError(''); setNotice(''); try {
        await work();
    }
    catch (e) {
        if (e instanceof ApiError && e.status === 401) {
            setSession(null);
            setCurrent(null);
            setProjects([]);
            setSelected(null);

        }
        setError(e instanceof Error ? e.message : '操作失败');
    }
    finally {
        setBusy(false);
    } }
    function goHome(){loadSequence.current++;setError('');setNotice('');navigate({view:'workbench'});}
    function closeDialog() { setDialog(null); setMember(null); setConflictRevision(null); }
    async function submitProject(e: FormEvent<HTMLFormElement>) { const values = formValues(e); await operation(async () => { const p = await save<Project>('/projects', 'POST', { code: values.get('code'), name: values.get('name') }); await refresh(); await openProject(p); closeDialog(); setNotice('项目已创建，请继续配置成员。'); }); }
    async function submitAccount(e: FormEvent<HTMLFormElement>) { const form = e.currentTarget, values = formValues(e); await operation(async () => { await save<Account>('/accounts', 'POST', { username: values.get('username'), display_name: values.get('display_name'), password: values.get('password') }); form.reset(); await refresh(); closeDialog(); setNotice('独立账号已创建，尚未获得任何项目权限。'); }); }
    async function submitMember(e: FormEvent<HTMLFormElement>) { const values = formValues(e); if (!selected)
        return; await operation(async () => { await save<Member>('/projects/' + selected.id + '/members', 'PUT', { account_id: accountId, roles, active: values.get('active') === 'on', revision: member?.revision ?? 0, valid_from: values.get('valid_from') ? new Date(String(values.get('valid_from')) + '+08:00').toISOString() : null, valid_until: values.get('valid_until') ? new Date(String(values.get('valid_until')) + '+08:00').toISOString() : null }); closeDialog(); await refresh(); await openProject(selected); setNotice('成员授权已保存；生效范围由服务端实时校验。'); }); }
    async function rename(e: FormEvent<HTMLFormElement>) { e.preventDefault(); if (!selected)
        return; await operation(async () => { try {
        await save<Project>('/projects/' + selected.id, 'PATCH', { name: draftName, revision: selected.revision });
        closeDialog();
        await refresh();
        await openProject(selected);
        setNotice('项目名称已更新。');
    }
    catch (e) {
        if (e instanceof ApiError && e.code === 'REVISION_CONFLICT')
            setConflictRevision(e.currentRevision ?? null);
        throw e;
    } }); }
    function openMember(m: Member | null) { setMember(m); setRoles(m?.roles ?? []); setAccountId(m?.account_id ?? ''); setDialog('member'); setError(''); }
    const labelFor = (id: string) => accounts.find(a => a.id === id)?.display_name ?? members.find(m => m.account_id === id)?.display_name ?? '历史账号';
    if (!ready)
        return <main className="loading" role="status">正在连接密灯…</main>;
    if (!session)
        return <>{error && <div className="connection-error" role="alert">{error}</div>}<Auth setup={setup} onLogin={s => { setSetup(false); signedIn(s); }}/></>;
    function changeWorkspaceProject(id:string){
        if(route.project)navigate({project:id,section:route.section??'requirements',tab:route.tab,panel:route.panel,desk:route.desk});
        else setWorkspaceProjectId(id);
    }
    function openFeature(section:keyof typeof sections,tab?:ViewRoute['tab'],panel?:ViewRoute['panel']){
        if(!workspaceProject)return;
        navigate({project:workspaceProject.id,section,tab,panel,
            object:section==='knowledge'&&route.section==='knowledge'&&route.project===workspaceProject.id?route.object:undefined,
            kind:section==='knowledge'&&route.section==='knowledge'&&route.project===workspaceProject.id&&route.object?'library':undefined});
    }
    const nav=<>
        <span className="nav-caption">工作空间</span>
        <button className={!route.project&&route.view!=='projects'?'nav active':'nav'} onClick={goHome}>知识问答工作台</button>
        <button className={!route.project&&route.view==='projects'?'nav active':'nav'} onClick={()=>navigate({view:'projects'})}>项目空间 <span>{projects.length}</span></button>
        <label className="workspace-project-picker">当前业务项目
            <select aria-label="当前业务项目" value={workspaceProject?.id??''} disabled={homeLoading||reading||busy||!projects.length} onChange={e=>changeWorkspaceProject(e.target.value)}>
                {!projects.length&&<option value="">{homeLoading?'正在读取项目…':'暂无可访问项目'}</option>}
                {projects.map(p=><option key={p.id} value={p.id}>{p.name} · {p.code}</option>)}
            </select>
        </label>
        <span className="nav-caption">业务功能</span>
        {Object.entries(businessDesks).map(([desk,label])=><button key={desk} disabled={homeLoading||reading||!workspaceProject} className={route.project&&route.desk===desk?'nav active':'nav'} onClick={()=>workspaceProject&&navigate({project:workspaceProject.id,section:'requirements',desk:desk as ViewRoute['desk']})}>{label}</button>)}
        {Object.entries(sections).map(([key,label])=><button disabled={homeLoading||!workspaceProject} className={route.project&&route.section===key&&!route.desk&&!route.panel&&!(key==='knowledge'&&route.tab==='applications')?'nav active':'nav'} key={key} onClick={()=>openFeature(key as keyof typeof sections)}>{label}</button>)}
        <button disabled={homeLoading||!workspaceProject} className={route.project&&route.section==='knowledge'&&route.tab==='applications'?'nav active':'nav'} onClick={()=>openFeature('knowledge','applications')}>应用生成 / 规则应用</button>
        <button disabled={homeLoading||!workspaceProject} className={route.panel==='members'?'nav active':'nav'} onClick={()=>openFeature('requirements',undefined,'members')}>项目成员与岗位</button>
        {!homeLoading&&!projects.length&&<p className="nav-empty-project">{session.account.is_admin?'暂无可访问项目，请从页面上方新建项目并配置成员。':'暂无可访问项目，请联系管理员将账号加入项目。'}</p>}
        <div className="side-summary"><span className="status-dot"/> 本机脱敏试点<p>依据版本协作，按本人岗位处理。</p></div>
    </>;
    return <div className="workspace"><header className="topbar"><div className="brand"><i/>密灯<span>嘉元项目协同中台</span></div><div className="identity"><button className="secondary compact mobile-navigation" onClick={()=>setDrawer(true)} aria-label="打开工作空间导航">导航</button><span>{session.account.display_name}<small>{session.account.is_admin?'管理员':'独立业务账号'}</small></span><button className="text-button" onClick={()=>void operation(async()=>{if(!window.dispatchEvent(new Event('mideng-before-navigate',{cancelable:true})))return;await request('/auth/logout',{method:'POST'});setSession(null);setCurrent(null);setWorkspaceProjectId('');setProjects([]);setSelected(null);setMembers([]);setAccounts([]);setAudit([]);setLink(null);navigate({view:'workbench'},true);})}>退出登录</button></div></header><Drawer title="工作空间导航" open={drawer} onClose={()=>setDrawer(false)} placement="left" width={290}>{nav}</Drawer><div className="workspace-body"><aside className="side">{nav}</aside><main className="content">
    {error&&<div role="alert" className="notice error">{error}</div>}{notice&&<div role="status" className="notice success">{notice}</div>}
    <div className="page-heading"><div><div className="eyebrow">{selected?'项目 / '+selected.code:'密灯 · 工作空间'}</div><h1>{selected?.name??(route.project?'项目空间':route.view==='projects'?'项目空间':'知识问答工作台')}</h1><p>{selected?'当前项目 · '+selected.roles.map(r=>r==='管理员'?'管理员（全流程办理）':r).join(' / '):'问知识、找依据，直接进入相关业务。'}</p></div><div className="heading-actions">{(route.project||route.error)&&<button className="secondary" onClick={goHome}>← 返回主界面</button>}<button className="secondary" disabled={busy||reading} onClick={()=>void operation(async()=>{await refresh();setReload(x=>x+1);setNotice('已重新读取当前授权范围。');})}>刷新</button>{session.account.is_admin&&<button className="secondary" onClick={()=>{setError('');setDialog('account');}}>创建账号</button>}{!route.project&&session.account.is_admin&&<button className="primary" onClick={()=>{setError('');setDialog('project');}}>＋ 新建项目</button>}</div></div>
    <RequestRecovery accountId={session.account.id} onNavigate={navigate}/>
    {route.error||readError?<section className="panel location-error"><h2>位置暂不可访问</h2><p role="alert">{route.error??readError}</p><button className="primary" onClick={goHome}>返回本人工作台</button><button className="secondary" onClick={()=>setReload(x=>x+1)}>重新读取</button></section>:reading?<p className="loading" role="status">正在校验项目、对象与来源版本…</p>:selected&&link?<>
    <nav className="breadcrumbs" aria-label="当前位置"><button onClick={goHome}>知识问答工作台</button><span>/</span><button onClick={()=>navigate({project:selected.id,section:route.section,desk:route.desk})}>{route.panel==='members'?'项目成员与岗位':route.desk?businessDesks[route.desk]:sections[route.section??'requirements']}</button>{link.object_id&&<><span>/</span><span>{link.title}</span></>}</nav>
    {route.panel==='members'?null:route.section==='knowledge'?<KnowledgeFlow key={session.account.id+':'+selected.id+':'+(route.object??'')+':'+(route.tab??'documents')} project={selected} members={members} accountId={session.account.id} route={route} onNavigate={navigate}/>:<Handoff key={selected.id} project={selected} members={members} accountId={session.account.id} target={link.object_id?{id:link.object_id,version:link.version_id,kind:link.kind}:null} route={route} onNavigate={navigate}/>}
    <details key={selected.id+':'+(route.panel??'')} open={route.panel==='members'?true:undefined} className="panel project-administration"><summary>项目成员与授权{selected.actions.includes('audit.read')?' / 操作记录':''}</summary><div className="section-heading"><div><h2>项目成员</h2><p>当前岗位与有效期由服务端校验。</p></div>{selected.actions.includes('project.edit')&&<button className="text-button" onClick={()=>{setDraftName(selected.name);setConflictRevision(null);setDialog('rename');}}>修改项目名称</button>}{session.account.is_admin&&<button className="primary compact" onClick={()=>openMember(null)}>＋ 配置成员</button>}</div><div className="table-scroll"><table><thead><tr><th>成员 / 独立账号</th><th>项目岗位</th><th>有效期与状态</th><th>操作</th></tr></thead><tbody>{members.map(m=><tr key={m.id}><td><strong>{m.display_name}</strong><small>{m.username}</small></td><td>{m.roles.map(r=><span key={r} className="pill">{r}</span>)}</td><td><span className={m.active?'status-ok':'status-muted'}>{!m.active?'已撤销':new Date(m.valid_from)>new Date()?'待生效':m.valid_until&&new Date(m.valid_until)<=new Date()?'已到期':'已启用'}</span><small>{localDate(m.valid_from)} 起{m.valid_until?'，至 '+localDate(m.valid_until):'，长期有效'}</small></td><td>{session.account.is_admin?<button className="text-button" onClick={()=>openMember(m)}>调整授权</button>:<span className="muted">管理员配置</span>}</td></tr>)}</tbody></table></div>{selected.actions.includes('audit.read')&&<details className="version-block"><summary>最近操作记录（100条）</summary><div className="audit-list">{audit.map(v=><div key={v.id}><span className="audit-marker"/><div><strong>{labelFor(v.actor_id)} · {actionName[v.action]??v.action}</strong><small>{localDate(v.at)}</small></div><code title={v.request_id}>请求 {v.request_id.slice(0,8)}</code></div>)}</div></details>}</details>
    </>:homeLoading?<p className="loading" role="status">正在读取本人工作空间…</p>:route.view==='projects'?<section className="project-grid">{projects.map(p=><button className="project-card" key={p.id} onClick={()=>void openProject(p)}><div className="card-top"><span className="project-symbol">项</span><span className="muted">↗</span></div><small>{p.code}</small><h2>{p.name}</h2><div>{p.roles.map(r=><span key={r} className="pill">{r}</span>)}</div><p>进入项目协作 →</p></button>)}{!projects.length&&<div className="empty-state"><h2>还没有可访问的项目</h2><p>{session.account.is_admin?'新建项目并配置同事岗位。':'请联系管理员，将你的独立账号加入项目。'}</p></div>}</section>:<Workbench key={session.account.id} project={workspaceProject} onProjectChange={changeWorkspaceProject} projects={projects} route={route} onNavigate={navigate} reload={reload}/>}
    <footer className="content-footer"><span>密灯 · 嘉元项目协同中台</span><span>当前职责 · 正式依据 · 交付留痕</span></footer></main></div><Modal open={dialog !== null} footer={null} title={dialog === 'project' ? '新建项目' : dialog === 'account' ? '创建独立账号' : dialog === 'rename' ? '修改项目名称' : '配置项目成员'} onCancel={closeDialog} destroyOnHidden>{error && <div role="alert" className="notice error">{error}</div>}{dialog === 'project' && <form className="modal-form" onSubmit={e => void submitProject(e)}><label>项目编码<input name="code" required placeholder="例如 JY-TEST-001"/></label><label>项目名称<input name="name" required maxLength={120} placeholder="填写合成或脱敏项目名"/></label><button className="primary" disabled={busy}>{busy ? '正在保存…' : '创建项目'}</button></form>}{dialog === 'account' && <form className="modal-form" onSubmit={e => void submitAccount(e)}><label>姓名<input name="display_name" required maxLength={80}/></label><label>账号<input name="username" required autoComplete="off"/></label><label>初始密码<input name="password" type="password" required minLength={6} maxLength={128} autoComplete="new-password"/></label><p className="fine">账号创建后不自动获得项目或业务签署权限，请通过安全渠道交接密码。</p><button className="primary" disabled={busy}>{busy ? '正在保存…' : '创建账号'}</button></form>}{dialog === 'rename' && <form className="modal-form" onSubmit={e => void rename(e)}><label>项目名称<input value={draftName} onChange={e => setDraftName(e.target.value)} maxLength={120} required/></label>{conflictRevision !== null && <div className="notice"><p>输入已保留；服务端当前版本为 r{conflictRevision}。</p><button type="button" className="text-button" onClick={() => void operation(async () => { if (selected)
        await openProject(selected); setConflictRevision(null); setNotice('已读最新版本，请核对保留的输入后再保存。'); })}>读取最新版本后核对</button></div>}<button className="primary" disabled={busy || conflictRevision !== null}>{busy ? '正在保存…' : '保存名称'}</button></form>}{dialog === 'member' && <form className="modal-form" onSubmit={e => void submitMember(e)}><label>独立账号<select required value={accountId} disabled={!!member} onChange={e => setAccountId(e.target.value)}><option value="">选择已创建的账号</option>{accounts.filter(a => member?.account_id === a.id || !members.some(m => m.account_id === a.id)).map(a => <option key={a.id} value={a.id}>{a.display_name}（{a.username}）</option>)}</select></label><label htmlFor="member-roles">项目岗位</label><Select id="member-roles" aria-label="项目岗位" mode="multiple" value={roles} onChange={setRoles} options={ROLES.map(r => ({ value: r, label: r }))} placeholder="选择实际负责的岗位"/><label>生效时间（上海时间）<input name="valid_from" type="datetime-local" defaultValue={member ? toInputTime(member.valid_from) : ''}/></label><label>失效时间（上海时间，可选）<input name="valid_until" type="datetime-local" defaultValue={member?.valid_until ? toInputTime(member.valid_until) : ''}/></label><label className="checkbox-label"><input name="active" type="checkbox" defaultChecked={member?.active ?? true}/>启用此项目授权</label><p className="fine">取消启用即撤销后续访问，历史记录保留。管理员岗位本身不具有财务发布或质量放行权。</p><button className="primary" disabled={busy || !roles.length || !accountId}>{busy ? '正在保存…' : '保存授权'}</button></form>}</Modal></div>;
}
function toInputTime(value: string) { const d = new Date(value); return new Date(d.getTime() + 8 * 60 * 60 * 1000).toISOString().slice(0, 16); }
