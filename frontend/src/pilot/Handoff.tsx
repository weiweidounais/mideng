import { useEffect, useCallback, useRef, useState, type FormEvent } from 'react';
import { Modal, Select } from 'antd';
import { ApiError, mutate, mutateForm, request, localDate, type Project, type Member } from './client';
import {ErrorDetails,RequestRecovery,useDraftGuard} from './FormSupport';
import { type Board, type BusinessDoc, type DocData, type RequirementData, type SchemeData, type BusinessVersion, type Contract, type MaterialRow, type FileItem, labels, inputTime, isoTime } from './handoff-types';
import './handoff.css';
import {BomEditor,ImportErrors} from './BomEditor';
import {validateBom,type BomError} from './form-rules';
import ProcurementFlow from './ProcurementFlow';
import {Pager} from './Workbench';
import {sections,sectionFor,type ViewRoute,type Section} from './navigation';
import ChangeFlow from './ChangeFlow';
import TraceFlow from './TraceFlow';
import CostFlow from './CostFlow';
import AssuranceFlow from './AssuranceFlow';
const empty: Board = { documents: [], contracts: [], rows: [], arrivals: [], issues: [], events: [] };
const reqBody: RequirementData = { title: '', summary: '', constraints: '', source: '', attachment_ids: [], brief_due_at: null, reply_due_at: null };
const schemeBody: SchemeData = { title: '', notes: '', risks: '', bom: [{ material: '', spec: '', quantity: '1', unit: '', need_by: '' }], attachment_ids: [], review_reason: '' };
type Dialog = {
    kind: 'withdraw';
    doc: BusinessDoc;
} | {
    kind: 'document';
    doc: BusinessDoc | null;
    parent: BusinessDoc | null;
    type: 'requirement' | 'scheme';
} | {
    kind: 'publish';
    doc: BusinessDoc;
} | {
    kind: 'contract';
    version: BusinessVersion;
} | {
    kind: 'action';
    contract: Contract;
    action: string;
} | {
    kind: 'row';
    row: MaterialRow;
} | {
    kind: 'arrival';
    row: MaterialRow;
};
export default function Handoff({ project, members, accountId, target, route, onNavigate }: {
    route:ViewRoute; onNavigate:(r:ViewRoute)=>void;
    project: Project;
    members: Member[];
    accountId: string;
    target: {
        id: string;
        version: string | null;
        kind?:string|null;
    } | null;
}) {
    const base = '/projects/' + project.id + '/handoff';
    const [board, setBoard] = useState<Board>(empty), [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
    const [selected, setSelected] = useState(''), [dialog, setDialog] = useState<Dialog | null>(null), [body, setBody] = useState<DocData>(reqBody), [files, setFiles] = useState<FileItem[]>([]), [recipients, setRecipients] = useState<string[]>([]), [proxies, setProxies] = useState<string[]>([]), [conflict, setConflict] = useState(false), [latestInfo, setLatestInfo] = useState('');
    type Tab='documents'|'contracts'|'changes'|'trace'|'cost'|'assurance';
    const tabs:Record<Section,Tab>={requirements:'documents',procurement:'contracts',changes:'changes',trace:'trace',cost:'cost',assurance:'assurance',knowledge:'documents'};
    const tab=tabs[route.section??'requirements'];
    function setTab(next:Tab){const section=(Object.keys(tabs) as Section[]).find(k=>tabs[k]===next)!;onNavigate({project:project.id,section});}
    function source(kind:string,id:string,version:string|null){onNavigate({project:project.id,section:sectionFor(kind),object:id,kind,version:version&&version!=='draft'?version:undefined});}
    type DocSummary={id:string;title:string;version_no:number;has_draft:boolean};
    const [index,setIndex]=useState<{items:DocSummary[];total:number}>({items:[],total:0}),[loading,setLoading]=useState(true),[loaded,setLoaded]=useState(false),[legacy,setLegacy]=useState(false);
    const readSequence=useRef(0);
    const [bomErrors,setBomErrors]=useState<BomError[]>([]),[importErrors,setImportErrors]=useState<{row:number;field:string;message:string}[]>([]);
    const [bomPreview, setBomPreview] = useState<SchemeData['bom'] | null>(null);
    const [failure,setFailure]=useState<unknown>(null);const guard=useDraftGuard(!!dialog,busy);
    const pending = useRef(new Map<string, string>());
    const role = (...roles: string[]) => roles.some(r => project.roles.includes(r));
    const who = (id: string) => members.find(m => m.account_id === id)?.display_name ?? '历史账号';
    const effective = (r: string) => members.filter(m => m.active && m.roles.includes(r) && new Date(m.valid_from) <= new Date() && (!m.valid_until || new Date(m.valid_until) > new Date()));
    const read=useCallback(async(signal?:AbortSignal)=>{
        const opts={signal};
        if(tab==='documents'){
            const idx=await request<typeof index>('/projects/'+project.id+'/workspace/documents?page='+(route.page??1),opts);
            const context=route.object?await request<Board>('/projects/'+project.id+'/workspace/document-context/'+route.object+(route.version?'?version_id='+encodeURIComponent(route.version):''),opts):empty;
            return {b:context,idx};
        }
        if(tab==='changes')return {b:await request<Board>('/projects/'+project.id+'/workspace/sources',opts),idx:{items:[],total:0}};
        if(tab==='contracts'&&(legacy||target?.kind==='contract'))return {b:await request<Board>(base+'/board',opts),idx:{items:[],total:0}};
        return {b:empty,idx:{items:[],total:0}};
    },[base,project.id,route.object,route.page,route.version,tab,legacy,target?.kind]);
    const apply=useCallback((result:{b:Board;idx:typeof index})=>{setBoard(result.b);setIndex(result.idx);const d=result.b.documents.find(d=>d.id===route.object);setSelected(d?.parent_id??d?.id??'');setLoaded(true);},[route.object]);
    useEffect(()=>{const c=new AbortController(),seq=++readSequence.current;setLoading(true);setLoaded(false);setError('');setBoard(empty);read(c.signal).then(r=>{if(!c.signal.aborted&&seq===readSequence.current)apply(r);}).catch(e=>{if(!c.signal.aborted)setError(e.message);}).finally(()=>{if(!c.signal.aborted)setLoading(false);});return()=>c.abort();},[read,apply]);
    useEffect(()=>{if(!loading&&target?.kind==='contract')document.getElementById('legacy-contract-'+target.id)?.scrollIntoView({block:'start'});},[loading,target?.kind,target?.id]);
    async function refresh(){const r=await read();apply(r);return r.b;}
    async function write<T>(suffix: string, method: string, payload: unknown) { const signature = method + suffix + JSON.stringify(payload), key = pending.current.get(signature) ?? crypto.randomUUID(); pending.current.set(signature, key); const r = await mutate<T>(base + suffix, method, payload, key); pending.current.delete(signature); return r; }
    async function run(work: () => Promise<void>) { if (busy)
        return; setBusy(true); setFailure(null); setError(''); setNotice(''); try {
        await work();
    }
    catch (e) {
        setFailure(e);if (e instanceof ApiError && e.code === 'REVISION_CONFLICT')
            setConflict(true);
        setError(e instanceof Error ? e.message : '操作失败');
    }
    finally {
        setBusy(false);
    } }
    function close() { setDialog(null); setConflict(false); setLatestInfo(''); setError(''); }
    function show(d: Dialog) { setBomErrors([]);setImportErrors([]);setBomPreview(null); setError(''); setNotice(''); setConflict(false); setLatestInfo(''); setRecipients([]); setProxies([]); setDialog(d); }
    async function edit(doc: BusinessDoc) { await run(async () => { const d = doc.has_draft ? doc : await write<BusinessDoc>('/documents/' + doc.id + '/revise', 'POST', { revision: doc.revision }); const parent = d.kind === 'scheme' ? board.documents.find(x => x.id === d.parent_id) ?? null : null; setBody(structuredClone(d.draft ?? d.versions[0].body)); setFiles(d.draft_files ?? d.versions[0]?.attachments ?? []); show({ kind: 'document', doc: d, parent, type: d.kind }); await refresh(); }); }
    function create(type: 'requirement' | 'scheme', parent: BusinessDoc | null = null) { setBody(structuredClone(type === 'requirement' ? reqBody : schemeBody)); setFiles([]); show({ kind: 'document', doc: null, parent, type }); }
    async function upload(file: File) { if (!dialog || dialog.kind !== 'document')
        return; await run(async () => { const form = new FormData(); form.append('file', file); form.append('kind', dialog.type); const f = await mutateForm<FileItem>(base+'/files',form,crypto.randomUUID()); setBody(b => ({ ...b, attachment_ids: [...b.attachment_ids, f.id] })); setFiles(fs => [...fs, f]); setNotice('附件已保存为受控原件。'); }); }
    async function previewBom(file: File) { await run(async () => { const form = new FormData(); form.append('file', file); const result = await request<{
        rows: SchemeData['bom'];
        errors: {
            row: number;
            field: string;
            message: string;
        }[];
    }>(base + '/bom-preview', { method: 'POST', body: form }); if (result.errors.length) {
        setBomPreview(null);setImportErrors(result.errors);throw new Error('CSV预检未通过，共'+result.errors.length+'项问题；当前草稿已保留。');
    } setImportErrors([]);setBomPreview(result.rows); }); }
    async function submit(e: FormEvent<HTMLFormElement>) {
        e.preventDefault();
        if (!dialog)
            return;
        const values = new FormData(e.currentTarget);
        await run(async () => {
            if (dialog.kind === 'document') {
                if('bom' in body){const errors=validateBom(body.bom);setBomErrors(errors);if(errors.length)throw new Error('BOM尚有未补齐字段，请核对全部料行后保存。');}
                const source = dialog.type === 'scheme' ? dialog.parent?.versions[0]?.id : null;
                const data = dialog.doc ? { revision: dialog.doc.revision, body, source_version_id: source } : { kind: dialog.type, body, parent_id: dialog.parent?.id ?? null, source_version_id: source };
                const d = await write<BusinessDoc>('/documents' + (dialog.doc ? '/' + dialog.doc.id : ''), dialog.doc ? 'PATCH' : 'POST', data);
                guard.complete();onNavigate({project:project.id,section:'requirements',object:d.id,kind:'document'});
            }
            else if (dialog.kind === 'withdraw')
                await write('/documents/' + dialog.doc.id + '/withdraw', 'POST', { revision: dialog.doc.revision, reason: values.get('reason') });
            else if (dialog.kind === 'publish')
                await write('/documents/' + dialog.doc.id + '/publish', 'POST', { revision: dialog.doc.revision, recipient_ids: recipients, diff_summary: values.get('diff_summary') });
            else if (dialog.kind === 'contract')
                await write('/contracts', 'POST', { version_id: dialog.version.id, recipient_id: values.get('recipient_id'), proxies, deliverable: values.get('deliverable'), quality_rule: values.get('quality_rule'), sla_hours: Number(values.get('sla_hours')), require_arrival: values.get('require_arrival') === 'on' });
            else if (dialog.kind === 'action')
                await write('/contracts/' + dialog.contract.id + '/actions', 'POST', { revision: dialog.contract.revision, action: dialog.action, reason: values.get('reason') ?? '', due_at: isoTime(String(values.get('due_at') ?? '')) });
            else if (dialog.kind === 'row')
                await write('/rows/' + dialog.row.id, 'PATCH', { revision: dialog.row.revision, state: values.get('state'), eta: values.get('eta') || null, blocked: values.get('blocked') === 'on', note: values.get('note') ?? '' });
            else
                await write('/rows/' + dialog.row.id + '/arrivals', 'POST', { revision: dialog.row.revision, quantity: values.get('quantity'), occurred_at: isoTime(String(values.get('occurred_at'))) });
            close();
            await refresh();
            setNotice('已保存至服务端，关联版本与操作记录已更新。');
        });
    }
    async function readLatest() { if (!dialog)
        return; await run(async () => { const b = await refresh(); if (dialog.kind === 'document' || dialog.kind === 'publish' || dialog.kind === 'withdraw') {
        const current = b.documents.find(d => d.id === dialog.doc?.id);
        if (current) {
            setDialog({ ...dialog, doc: current });
            setLatestInfo(JSON.stringify(current.draft ?? current.versions[0]?.body, null, 2));
        }
    }
    else if (dialog.kind === 'action') {
        const c = b.contracts.find(c => c.id === dialog.contract.id);
        if (c)
            setDialog({ ...dialog, contract: c });
    }
    else if (dialog.kind === 'row' || dialog.kind === 'arrival') {
        const r = b.rows.find(r => r.id === dialog.row.id);
        if (r)
            setDialog({ ...dialog, row: r });
    } setConflict(false); }); }
    const doc = board.documents.find(d => d.id === selected), requirements = index.items;
    const docTitle = (d: BusinessDoc) => (d.draft ?? d.versions[0]?.body)?.title ?? '未命名文档';
    const contractSource = (c: Contract) => { const scheme = board.documents.find(d => d.versions.some(v => v.id === c.version_id)); const v = scheme?.versions.find(v => v.id === c.version_id); const reqVersion = board.documents.flatMap(d => d.versions).find(r => r.id === v?.source_version_id); return v ? `${v.body.title} · 方案/BOM v${v.number} · 需求 v${reqVersion?.number ?? '历史'}` : '历史正式版本'; };
    const actionLabels: Record<string, string> = { issue: '发出交接', submit: '提交交付', accept: '验收交付', return: '退回重交', close: '关闭交接', pause: '暂停', resume: '恢复', cancel: '取消交接', reschedule: '修订时限' };
    return <section className="handoff"><div className="section-heading"><div><h2>{sections[route.section??'requirements']}</h2><p>正式版本连到具体交付，采购进度与交付质量分别确认。</p></div><div className="heading-actions"><button className="secondary compact" disabled={busy} onClick={() => void run(async () => { await refresh(); setNotice('业务数据已刷新。'); })}>刷新业务</button>{tab==='documents' && role('市场', '商务') && <button className="primary compact" onClick={() => create('requirement')}>＋ 新建需求</button>}</div></div>{error && !dialog && <div className="notice error" role="alert">{error}</div>}{notice && <div className="notice success" role="status">{notice}</div>}{board.issues.length > 0 && <div className="issue-box"><strong>待处理例外 · {board.issues.length}</strong>{board.issues.map(i => <div key={i.id}>{i.title}<small>责任人：{who(i.owner_id)}</small></div>)}</div>}<nav className="business-tabs" aria-label="业务板块"><button className={tab === 'documents' ? 'active' : ''} onClick={() => setTab('documents')}>需求与方案 </button><button className={tab === 'contracts' ? 'active' : ''} onClick={() => setTab('contracts')}>交接与采购</button><button className={tab === 'changes' ? 'active' : ''} onClick={() => setTab('changes')}>变更与处置</button><button className={tab==='trace'?'active':''} onClick={()=>setTab('trace')}>管段与质量</button><button className={tab==='cost'?'active':''} onClick={()=>setTab('cost')}>成本与月结</button><button className={tab==='assurance'?'active':''} onClick={()=>setTab('assurance')}>异常与证据</button></nav>{loading?<p role="status" className="empty-copy">正在读取当前板块…</p>:!loaded?<p className="empty-copy">读取未完成，请刷新重试。</p>:tab === 'assurance' ? <AssuranceFlow accountId={accountId} project={project} members={members} target={target} onSource={source}/> : tab === 'cost' ? <CostFlow project={project} members={members} target={target} onNavigate={onNavigate}/> : tab === 'trace' ? <TraceFlow project={project} members={members} accountId={accountId} route={route} onNavigate={onNavigate} target={target} onChange={id=>source('change',id,null)}/> : tab === 'changes' ? <ChangeFlow project={project} members={members} accountId={accountId} board={board} target={target}/> : tab === 'documents' ? <div className="document-layout"><div className="document-list">{requirements.length ? requirements.map(d => <button key={d.id} className={d.id === selected ? 'selected' : ''} onClick={() => source('document',d.id,null)}><strong>{d.title}</strong><small>{d.version_no ? '正式 v' + d.version_no : '尚未正式发布'}{d.has_draft ? ' · 草稿待处理' : ''}</small></button>) : <p className="empty-copy">还没有需求。由市场录入，商务检查并发布。</p>}<Pager page={route.page??1} total={index.total} onPage={page=>onNavigate({...route,page,object:undefined,version:undefined,kind:undefined})}/></div><div className="document-detail">{doc ? <><div className="business-heading"><div><span className="pill">需求 · r{doc.revision}</span><h3>{docTitle(doc)}</h3></div><div className="heading-actions">{role('市场', '商务') && <button className="secondary compact" onClick={() => void edit(doc)}>{doc.has_draft ? '编辑草稿' : '创建修订草稿'}</button>}{doc.versions[0]?.current && role('商务') && <button className="text-button" onClick={() => show({ kind: 'withdraw', doc })}>撤销当前正式版</button>}{doc.has_draft && role('商务') && <button className="primary compact" onClick={() => show({ kind: 'publish', doc })}>发布正式需求</button>}{doc.versions[0]?.current && role('设计') && <button className="primary compact" onClick={() => create('scheme', doc)}>回写方案/BOM</button>}</div></div>{doc.draft && <details open className="version-block draft"><summary>修订草稿 · 尚未成为执行依据</summary><DocumentContent body={doc.draft}/><Files items={doc.draft_files ?? []} base={base}/></details>}{doc.versions.map(v => <details key={v.id} className="version-block" open={v.current || target?.version === v.id}><summary>正式需求 v{v.number} · {v.withdrawn ? '已撤销' : v.current ? '当前依据' : '历史版本'} <small>{localDate(v.published_at)}</small></summary><p className="version-note">发布：{who(v.published_by)} · 差异：{v.diff_summary}</p><DocumentContent body={v.body}/><Files items={v.attachments} base={base}/></details>)}<h3 className="subheading">关联方案 / BOM</h3>{board.documents.filter(d => d.parent_id === doc.id).map(s => <section key={s.id} className="scheme-card"><div className="business-heading"><div><strong>{docTitle(s)}</strong>{s.needs_review && <span className="warning-pill">需求已更新，需复核</span>}<small>绑定需求版本：{doc.versions.find(v => v.id === s.source_version_id)?.number ?? '历史'} · r{s.revision}</small></div><div className="heading-actions">{role('设计') && <button className="secondary compact" onClick={() => void edit(s)}>{s.has_draft ? '编辑/复核草稿' : '起修订并复核'}</button>}{s.versions[0]?.current && role('设计') && <button className="text-button" onClick={() => show({ kind: 'withdraw', doc: s })}>撤销当前正式版</button>}{s.has_draft && role('设计') && <button className="primary compact" onClick={() => show({ kind: 'publish', doc: s })}>发布方案/BOM</button>}</div></div>{s.draft && <details className="version-block draft" open><summary>方案草稿</summary><DocumentContent body={s.draft}/><Files items={s.draft_files ?? []} base={base}/></details>}{s.versions.map(v => <details key={v.id} className="version-block" open={v.current || target?.version === v.id}><summary>正式方案/BOM v{v.number} · {v.withdrawn ? '已撤销' : v.current ? '有效' : '历史/待复核'}</summary><p className="version-note">{who(v.published_by)} · {localDate(v.published_at)} · {v.diff_summary}</p><DocumentContent body={v.body}/><Files items={v.attachments} base={base}/>{v.current && <button className="secondary compact" onClick={() => setTab('contracts')}>进入采购闭环</button>}</details>)}</section>)}{!board.documents.some(d => d.parent_id === doc.id) && <p className="empty-copy">设计尚未回写方案。</p>}</> : <div className="empty-copy">选择一份需求，查看草稿、正式版本和设计回写。</div>}</div></div> : <><ProcurementFlow project={project} members={members} accountId={accountId} target={target} route={route} onNavigate={onNavigate} onChange={id=>source('change',id,null)}/>{!legacy&&target?.kind!=='contract'&&<button className="secondary compact" onClick={()=>setLegacy(true)}>查看历史交接记录</button>}{board.contracts.length>0&&<details open={legacy||target?.kind==='contract'} className="version-block"><summary>历史交接记录（旧流程，保留原始事实）</summary>{board.contracts.map(c=><section className="contract-card" id={'legacy-contract-'+c.id} key={c.id}><span className="pill">{labels[c.state]??c.state}</span><h3>{c.deliverable}</h3><p>{contractSource(c)}</p><p>设计：{who(c.created_by)}；原采购接收人：{who(c.recipient_id)}；退回{c.return_count}次</p><p>质量规则：{c.quality_rule}</p><p>旧流程记录不代表已完成新流程的项目经理复核、材料质检或商务归档。</p>{board.rows.filter(r=>r.contract_id===c.id).map(r=><p key={r.id}>{r.material} / {r.spec} · 约定{r.quantity}、实到{r.arrived} {r.unit}</p>)}<details><summary>历史操作</summary>{board.events.filter(e=>e.object_id===c.id).map(e=><p key={e.id}>{localDate(e.at)} · {who(e.actor_id)} · {e.action}</p>)}</details></section>)}</details>}</>}
 <Modal open={dialog !== null} title={dialog?.kind === 'document' ? (dialog.type === 'requirement' ? '需求草稿' : '方案/BOM草稿') : dialog?.kind === 'withdraw' ? '撤销当前正式版' : dialog?.kind === 'publish' ? '发布正式版本' : dialog?.kind === 'contract' ? '创建版本交接' : dialog?.kind === 'action' ? actionLabels[dialog.action] : dialog?.kind === 'row' ? '更新采购进度' : '登记分批到货'} footer={null} onCancel={()=>guard.close(close)} destroyOnHidden width={dialog?.kind === 'document' ? 820 : 560}>{error && <div className="notice error" role="alert">{error}</div>}{conflict && <button className="secondary" onClick={() => void readLatest()}>读取最新版本后核对（保留输入）</button>}{latestInfo && <details><summary>服务端最新内容，请与保留输入核对</summary><pre className="latest-info">{latestInfo}</pre></details>}<ErrorDetails error={failure}/><RequestRecovery accountId=""/><form className="modal-form" onChangeCapture={guard.mark} onSubmit={e => void submit(e)}>{dialog?.kind === 'document' && <><label>标题<input required maxLength={120} value={body.title} onChange={e => setBody({ ...body, title: e.target.value })}/></label>{dialog.type === 'requirement' && 'summary' in body ? <><label>需求正文<textarea required rows={5} maxLength={8000} value={body.summary} onChange={e => setBody({ ...body, summary: e.target.value })}/></label><label>约束<textarea rows={2} maxLength={4000} value={body.constraints} onChange={e => setBody({ ...body, constraints: e.target.value })}/></label><label>来源依据<input required maxLength={1000} value={body.source} onChange={e => setBody({ ...body, source: e.target.value })}/></label><label>交底期限（上海时间，可选）<input type="datetime-local" value={body.brief_due_at ? inputTime(body.brief_due_at) : ''} onChange={e => setBody({ ...body, brief_due_at: isoTime(e.target.value) })}/></label><label>设计回写期限（上海时间，可选）<input type="datetime-local" value={body.reply_due_at ? inputTime(body.reply_due_at) : ''} onChange={e => setBody({ ...body, reply_due_at: isoTime(e.target.value) })}/></label></> : 'notes' in body ? <><p className="notice">本次依据：{dialog.parent?.versions[0]?.body.title} · 正式需求 v{dialog.parent?.versions[0]?.number}</p><label>方案要点<textarea required rows={4} maxLength={8000} value={body.notes} onChange={e => setBody({ ...body, notes: e.target.value })}/></label><label>风险与限制<textarea rows={2} value={body.risks} onChange={e => setBody({ ...body, risks: e.target.value })}/></label><label>复核结论 / 无影响依据<input value={body.review_reason} required={dialog.doc?.needs_review} onChange={e => setBody({ ...body, review_reason: e.target.value })} placeholder="需求升版后须明确填写"/></label><h3>BOM 料行</h3><div className="notice"><a download="BOM模板.csv" href={'data:text/csv;charset=utf-8,' + encodeURIComponent('\ufeff物料,规格,数量,单位,需用日期\n示例管材,DN100,1,米,2026-12-01\n')}>下载CSV模板</a><label>预检导入CSV料表<input type="file" accept=".csv" disabled={busy} onChange={e => { const f = e.target.files?.[0]; if (f)
        void previewBom(f); e.target.value = ''; }}/></label>{importErrors.length>0&&<ImportErrors key={importErrors.length} errors={importErrors}/>} {bomPreview && <><p>已预检 {bomPreview.length} 行；尚未替换当前草稿。</p><button type="button" className="secondary" onClick={() => { setBody({ ...body, bom: bomPreview }); setBomPreview(null); }}>确认应用至当前BOM草稿</button></>}</div><BomEditor lines={body.bom} errors={bomErrors} onChange={bom=>{setBody({...body,bom});setBomErrors([]);}}/><button type="button" className="secondary" onClick={() => setBody({ ...body, bom: [...body.bom, ...structuredClone(schemeBody.bom)] })}>＋ 添加料行</button></> : null}<label className="file-input">附件原件<input type="file" accept=".pdf,.docx,.xlsx,.png,.jpg,.jpeg,.txt,.md,.csv" disabled={busy} onChange={e => { const file = e.target.files?.[0]; if (file)
        void upload(file); e.target.value = ''; }}/></label><Files items={files.filter(f => body.attachment_ids.includes(f.id))} base={base}/><p className="fine">附件不超过20MB。仅上传测试或获准脱敏资料，发布后冻结原件哈希。</p></>}
 {dialog?.kind === 'withdraw' && <><p className="notice">保留当前正式版本与历史证据，引用该版的交接将拦截新执行，不删除已发生事实。</p><label>撤销依据<textarea name="reason" required maxLength={1000} rows={3}/></label></>}
 {dialog?.kind === 'publish' && <><p className="notice">即将发布：{dialog.doc.draft?.title} · v{dialog.doc.version_no + 1}；正式快照不可覆盖。</p><details><summary>核对待发布内容</summary>{dialog.doc.draft && <DocumentContent body={dialog.doc.draft}/>}</details><label htmlFor="publish-recipients">必需接收人（{dialog.doc.kind === 'requirement' ? '设计' : '项目经理'}）</label><Select id="publish-recipients" aria-label="必需接收人" mode="multiple" value={recipients} onChange={setRecipients} options={effective(dialog.doc.kind === 'requirement' ? '设计' : '项目经理').map(m => ({ value: m.account_id, label: m.display_name + '（' + m.roles.join('/') + '）' }))}/><label>发布 / 差异说明<textarea name="diff_summary" required maxLength={1000} rows={3}/></label></>}
 {dialog?.kind === 'contract' && <><p className="notice">绑定方案/BOM v{dialog.version.number}：{dialog.version.body.title}</p><label>采购接收人<select name="recipient_id" required><option value="">选择有授权的采购账号</option>{effective('采购').map(m => <option key={m.id} value={m.account_id}>{m.display_name}</option>)}</select></label><label htmlFor="procurement-proxies">授权采购代理（可选）</label><Select id="procurement-proxies" aria-label="授权采购代理" mode="multiple" value={proxies} onChange={setProxies} options={effective('采购').map(m => ({ value: m.account_id, label: m.display_name }))}/><label>交付物<input name="deliverable" required defaultValue="方案与BOM交付"/></label><label>质量验收规则<textarea name="quality_rule" required defaultValue="核对完整性、正式版本、规格、数量/单位与需用日期"/></label><label>交付时限（从BOM发布算自然小时）<input type="number" name="sla_hours" min={1} max={720} required defaultValue={24}/></label><label className="checkbox-label"><input name="require_arrival" type="checkbox"/>关闭前必须全量到货</label></>}
 {dialog?.kind === 'action' && <><p>{actionLabels[dialog.action]}：{dialog.contract.deliverable} · 当前 {labels[dialog.contract.state]}</p><label>说明 / 依据<textarea name="reason" required={['return', 'pause', 'resume', 'cancel', 'reschedule'].includes(dialog.action)} rows={3} maxLength={1000}/></label>{dialog.action === 'reschedule' && <label>新截止时间（上海时间）<input type="datetime-local" name="due_at" defaultValue={inputTime(dialog.contract.due_at)} required/></label>}{dialog.action === 'accept' && <p className="fine">确认设计交付满足质量规则；物料到货另行登记。</p>}</>}
 {dialog?.kind === 'row' && <><p>{dialog.row.material} · {dialog.row.spec} · 实到 {dialog.row.arrived}/{dialog.row.quantity}{dialog.row.unit}</p><label>采购进度<select name="state" defaultValue={dialog.row.state}>{['pending', 'quoted', 'ordered', 'arrived'].map(s => <option key={s} value={s}>{s === 'pending' ? '待处理' : labels[s]}</option>)}</select></label><label>ETA<input type="date" name="eta" defaultValue={dialog.row.eta ?? ''}/></label><label className="checkbox-label"><input name="blocked" type="checkbox" defaultChecked={dialog.row.blocked}/>当前存在阻塞</label><label>说明 / 阻塞与解除依据<textarea name="note" defaultValue={dialog.row.note} maxLength={1000}/></label></>}
 {dialog?.kind === 'arrival' && <><p>{dialog.row.material} · 实到 {dialog.row.arrived}/{dialog.row.quantity}{dialog.row.unit}</p><label>本批实际数量<input name="quantity" type="number" min="0.000001" step="0.000001" required/></label><label>实际到货时间（上海时间）<input name="occurred_at" type="datetime-local" required defaultValue={inputTime(new Date().toISOString())}/></label><p className="fine">分批数量确定性累加，未足量不完成；重复提交不重复入库。</p></>}
 <button className="primary" disabled={busy || conflict || (dialog?.kind === 'publish' && !recipients.length)}>{busy ? '正在保存…' : dialog?.kind === 'publish' ? '确认发布正式版本' : '确认保存'}</button></form></Modal></section>;
}
function DocumentContent({ body }: {
    body: DocData;
}) { const [page,setPage]=useState(1);return <div className="document-content">{'summary' in body ? <><p className="preserve">{body.summary}</p><p className="preserve">约束：{body.constraints || '无补充'}</p><small>来源：{body.source}</small></> : <><p className="preserve">{body.notes}</p><p className="preserve">风险：{body.risks || '无补充'}</p>{body.review_reason && <p>复核：{body.review_reason}</p>}<div className="table-scroll"><table><thead><tr><th>物料</th><th>规格</th><th>数量/单位</th><th>需用</th></tr></thead><tbody>{body.bom.slice((page-1)*20,page*20).map((r, i) => <tr key={i}><td>{r.material}</td><td>{r.spec}</td><td>{r.quantity} {r.unit}</td><td>{r.need_by}</td></tr>)}</tbody></table></div><Pager page={page} total={body.bom.length} onPage={setPage}/></>}</div>; }
function Files({ items, base }: {
    items: FileItem[];
    base: string;
}) { return <div className="attachment-list">{items.map(f => <a key={f.id} href={'/api' + base + '/files/' + f.id} target="_blank" rel="noreferrer">↧ {f.name}<small>SHA-256 {f.sha256.slice(0, 12)}… · {f.size} 字节</small></a>)}</div>; }
