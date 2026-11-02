import {useCallback, useEffect, useState} from 'react';
import {Alert, Button, Form, Input, InputNumber, Modal, Select, Space, Switch, Table, Tabs, Tag, Typography} from 'antd';
import {api, ApiError, json} from '../api';
import {downloadText, EmptyState, PageTitle, SectionCard} from '../components/ui';
import {useApp} from '../store';
import './collaboration.css';

type WorkRole = 'market' | 'business' | 'project_manager' | 'design' | 'purchase';
type Entity = {id: string; revision: number};
type Project = Entity & {name: string; code: string; processOwner: string; dataOwner: string; roles: WorkRole[]; legacy?: boolean};
type Access = {principal: string; admin: boolean; projects: Project[]};
type History = {at: string; by: string; action: string; detail?: string};
type Requirement = Entity & {ownerName: string; summary: string; constraints: string; attachments: string[]; dueHint: string;
  status: string; version: number; schemeNotes: string; schemeVersion: number; changeReason?: string; history?: History[]};
type Contract = Entity & {name: string; deliverable: string; trigger: string; qualityRule: string; designOwner: string;
  purchaseOwner: string; escalateTo: string; dueAt: string; status: string; basisVersion: number; needsReview: boolean; overdue: boolean; note: string; evidence: string};
type Bom = Entity & {materialCode: string; materialName: string; spec: string; qty: string; unit: string; needBy: string;
  status: string; eta: string; sourceRef: string; basisVersion: number; needsReview: boolean; note: string};
type Decision = Entity & {title: string; options: string; decision: string; ownerName: string; dueAt: string; evidence: string; status: string; result: string; resultEvidence?: string};
type Exception = {id: string; type: string; title: string; owner: string; ownerRole: WorkRole; dueAt: string};
type Event = Entity & {at: string; role: string; action: string; detail: string; recordId: string};
type Board = {packages: Requirement[]; contracts: Contract[]; bom: Bom[]; decisions: Decision[]; exceptions: Exception[]; events: Event[]};
type Member = Entity & {principal: string; name: string; roles: WorkRole[]};
type Values = Record<string, string | number | string[] | boolean>;
type Field = {name: string; label: string; kind?: 'textarea' | 'number' | 'date' | 'select' | 'roles'; optional?: boolean; options?: {value: string; label: string}[]};
type Dialog = {title: string; fields: Field[]; initial?: Values; submit: (values: Values) => Promise<boolean>};
const labels: Record<WorkRole, string> = {market: '市场', business: '商务', project_manager: '项目经理', design: '设计', purchase: '采购'};
const roleOptions = Object.entries(labels).map(([value, label]) => ({value, label}));
const names: Record<string, string> = {draft: '待交底草稿', changed: '变更待交底', briefed: '已交底', open: '待处理',
  in_progress: '处理中', delivered: '待采购验收', returned: '退回补齐', closed: '已完成', pending: '待询价', quoted: '已询价', ordered: '已下单', arrived: '已到货', blocked: '阻塞'};
const emptyBoard: Board = {packages: [], contracts: [], bom: [], decisions: [], exceptions: [], events: []};
const stamp = (s?: string) => s ? new Date(s).toLocaleString('zh-CN', {hour12: false}) : '未登记';
const field = (name: string, label: string, kind?: Field['kind'], optional = false): Field => ({name, label, kind, optional});
const status = (v: string) => <Tag color={['blocked', 'returned', 'changed'].includes(v) ? 'warning' : 'blue'}>{names[v] || v}</Tag>;

export default function CollaborationPage() {
  const {role: loginRole} = useApp();
  const [access, setAccess] = useState<Access>({principal: '', admin: false, projects: []});
  const [projectId, setProjectId] = useState('');
  const [workRole, setWorkRole] = useState<WorkRole>('project_manager');
  const [board, setBoard] = useState<Board>(emptyBoard);
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [mineOnly, setMineOnly] = useState(false);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [form] = Form.useForm<Values>();
  const [tab, setTab] = useState(() => location.hash.includes('requirements') ? 'packages' : location.hash.includes('contracts') ? 'contracts' : 'exceptions');
  const project = access.projects.find(p => p.id === projectId);
  const roles = project?.roles || [];
  const loadAccess = useCallback(async () => {
    const data = await api<Access>('/collaboration/access'); setAccess(data);
    setProjectId(old => data.projects.some(p => p.id === old) ? old : data.projects[0]?.id || '');
  }, []);
  const load = useCallback(async () => {
    if (!projectId) return;
    const [data, people] = await Promise.all([api<Board>(`/collaboration/board?projectId=${encodeURIComponent(projectId)}`),
      access.admin ? api<Member[]>(`/collaboration/projects/${projectId}/members`) : Promise.resolve([])]);
    setBoard(data); setMembers(people);
  }, [projectId, access.admin]);
  useEffect(() => {
    let active = true;
    setAccess({principal: '', admin: false, projects: []}); setProjectId(''); setBoard(emptyBoard);
    void api<Access>('/collaboration/access').then(data => {if (active) {setAccess(data); setProjectId(data.projects[0]?.id || '');}})
      .catch(e => {if (active) setError((e as Error).message);});
    return () => {active = false;};
  }, [loginRole]);
  useEffect(() => {if (roles.length && !roles.includes(workRole)) setWorkRole(roles[0]);}, [project, workRole]);
  useEffect(() => {
    let active = true; setBoard(emptyBoard); setMembers([]);
    if (!projectId) return;
    setLoading(true);
    void Promise.all([api<Board>(`/collaboration/board?projectId=${encodeURIComponent(projectId)}`),
      access.admin ? api<Member[]>(`/collaboration/projects/${projectId}/members`) : Promise.resolve([])])
      .then(([data, people]) => {if (active) {setBoard(data); setMembers(people);}})
      .catch(e => {if (active) setError((e as Error).message);})
      .finally(() => {if (active) setLoading(false);});
    return () => {active = false;};
  }, [projectId, access.admin]);
  const run = async (path: string, method: string, body: unknown) => {
    setBusy(true); setError('');
    try {
      await api('/collaboration/' + path, {...json(method, body), headers: {'X-Collaboration-Role': workRole}});
      await loadAccess(); await load(); return true;
    } catch (e) {
      setError((e as Error).message);
      if (e instanceof ApiError && [403, 409].includes(e.status)) {try {await loadAccess(); await load();} catch {setBoard(emptyBoard);}}
      return false;
    } finally {setBusy(false);}
  };
  const open = (value: Dialog) => {form.resetFields(); form.setFieldsValue(value.initial || {}); setDialog(value);};
  const edit = (path: string, row: Entity, title: string, fields: Field[], initial?: Values, extra?: Values) =>
    open({title, fields, initial, submit: v => run(`${path}/${row.id}`, 'PATCH', {expectedRevision: row.revision, ...v, ...extra})});
  const selectReq: Field = {name: 'reqPackageId', label: '需求依据', kind: 'select', options: board.packages
    .filter(p => p.status === 'briefed' && p.schemeVersion === p.version).map(p => ({value: p.id, label: `v${p.version} · ${p.summary.slice(0, 50)}`}))};
  const selectContract: Field = {name: 'ifaceId', label: '设计采购契约', kind: 'select', options: board.contracts
    .filter(c => !c.needsReview).map(c => ({value: c.id, label: `${c.name} · v${c.basisVersion}`}))};
  const contractAction = (r: Contract, next: string) => edit('contracts', r, next === 'delivered' ? '提交设计交付 / 重新核对版本' : next === 'closed' ? '采购确认验收' : '退回设计补齐',
    [field('note', '说明 / 验收结论', 'textarea'), ...(next === 'delivered' ? [field('evidence', '交付证据编号 / 文件位置')] : [])],
    next === 'delivered' ? {evidence: r.evidence || ''} : {}, {status: next});
  const purchaseAction = (r: Bom, next?: string) => edit('bom', r, next ? `登记${names[next]}` : '更新交期与说明',
    [field('note', '人工核对结果 / 阻塞原因', 'textarea'), field('eta', '预计到货日期', 'date', true),
      field('sourceRef', '原系统订单 / 收货凭证编号', undefined, !['ordered', 'arrived'].includes(next || ''))],
    {eta: r.eta || '', sourceRef: r.sourceRef || ''}, next ? {status: next} : {});
  const authorize = (m?: Member) => open({title: '项目成员授权（空角色列表表示撤销）', fields: [field('principal', '成员在本页看到的身份编号'),
    field('name', '成员姓名'), {name: 'roles', label: '允许的工作角色', kind: 'roles', optional: true}], initial: m ? {principal: m.principal, name: m.name, roles: m.roles} : {roles: []},
    submit: v => run(`projects/${projectId}/members`, 'PUT', {...v, roles: v.roles || [], expectedRevision: members.find(x => x.principal === v.principal)?.revision || 0})});
  const refresh = async () => {setLoading(true); setError(''); try {await loadAccess(); await load();} catch (e) {setError((e as Error).message); setBoard(emptyBoard);} finally {setLoading(false);}};
  const exportProject = async () => {try {const data = await api(`/collaboration/projects/${projectId}/export`); downloadText(`${project?.code}-协同记录.json`, JSON.stringify(data, null, 2), 'application/json');} catch (e) {setError((e as Error).message);}};
  const exceptions = mineOnly && workRole !== 'project_manager' ? board.exceptions.filter(e => e.ownerRole === workRole) : board.exceptions;

  return <div className="collab-page page-content">
    <PageTitle eyebrow="COLLABORATION · PILOT" title="协同工作台" description="需求交底 → 设计交付 → 采购验收 → 例外与人工决策。" actions={<Space wrap>
      <Select aria-label="项目" placeholder="选择项目" value={projectId || undefined} style={{width: 230}} options={access.projects.map(p => ({value: p.id, label: `${p.code} · ${p.name}`}))} onChange={v => {setDialog(null); setProjectId(v);}}/>
      <Select aria-label="工作角色" value={roles.includes(workRole) ? workRole : undefined} placeholder="待授权" style={{width: 120}} options={roles.map(value => ({value, label: labels[value]}))} onChange={setWorkRole}/>
      <Button loading={loading} onClick={() => void refresh()}>刷新</Button>
      {access.admin && <Button onClick={() => open({title: '建立项目责任档案', fields: [field('code', '项目编码（字母、数字、横线）'), field('name', '项目名称'), field('processOwner', '流程责任人'), field('dataOwner', '数据责任人')], submit: v => run('projects', 'POST', v)})}>新建项目</Button>}
    </Space>}/>
    <Alert className="collab-role-hint" type="info" showIcon message="权限由服务端校验；仅显示已授权项目和角色" description={<span>当前浏览器身份编号：<Typography.Text copyable>{access.principal || '加载中'}</Typography.Text>。请管理员按此编号授权。当前使用浏览器身份与管理口令；浏览器更换或人员离职需重新核对授权。</span>}/>
    {error && <Alert role="alert" type="error" showIcon message={error} closable onClose={() => setError('')} style={{marginBottom: 16}}/>}
    {!project ? <EmptyState title="暂无已授权项目" description={access.admin ? '先建立项目并明确流程、数据责任人，再给成员授权。' : '复制上面的身份编号给管理员；授权后点击刷新。'}/> : <>
      <SectionCard title={`${project.code} · ${project.name}`} subtitle={`流程责任人：${project.processOwner} ｜ 数据责任人：${project.dataOwner}`}>
        <p>财务、物料及订单以用友 / ERP 原系统为准；这里登记协同和人工核对结果。节省工时、收益与 ROI：待实测。</p>
        {project.legacy && <Alert type="warning" message="历史数据已保留，原有交付依据需要重新核对。"/>}<Space wrap><Button onClick={() => void exportProject()}>导出本项目记录</Button>
          {access.admin && <Button onClick={() => edit('projects', project, '确认项目责任人', [field('processOwner', '流程责任人'), field('dataOwner', '数据责任人')], {processOwner: project.processOwner, dataOwner: project.dataOwner})}>确认责任人</Button>}</Space>
      </SectionCard>
      <div className="collab-metrics" style={{marginTop: 16}}>{[[exceptions.length, '例外待办'], [board.packages.filter(p => p.status !== 'briefed').length, '待交底版本'],
        [board.contracts.filter(c => c.overdue).length, '超时交付'], [board.bom.filter(b => b.needsReview).length, '依据待复核料表']].map(([n, title]) => <div key={title}><b>{n}</b><span>{title}</span></div>)}</div>
      <Tabs activeKey={tab} onChange={setTab} items={[
        {key: 'exceptions', label: '例外 / 待办', children: <SectionCard title="需要人处理的断点" subtitle="明确责任、到期时间与下一步处理" action={<Space>只看当前角色<Switch aria-label="只看当前角色" checked={mineOnly} onChange={setMineOnly}/></Space>}>
          <Table<Exception> loading={loading} rowKey="id" dataSource={exceptions} scroll={{x: 760}} columns={[{title: '类型', dataIndex: 'type'}, {title: '下一步', dataIndex: 'title'}, {title: '责任人', dataIndex: 'owner'}, {title: '到期', dataIndex: 'dueAt', render: v => v ? stamp(v) : '按交底约定'}]}/></SectionCard>},
        {key: 'packages', label: '需求交底', children: <SectionCard title="同版本需求依据" subtitle="发布后由商务登记变更升版；旧方案与记录保留" action={workRole === 'market' && <Button type="primary" onClick={() => open({title: '录入需求草稿', fields: [field('ownerName', '客户需求确认人'), field('summary', '需求要点', 'textarea'), field('constraints', '工期、规格、范围约束', 'textarea', true), field('attachmentsText', '证据编号 / 文件位置（每行一条）', 'textarea', true), field('dueHint', '响应时间约定', undefined, true)], submit: v => {const {attachmentsText, ...rest} = v; return run('packages', 'POST', {...rest, projectId, attachments: String(attachmentsText || '').split('\n').map(s => s.trim()).filter(Boolean)});}})}>录入需求</Button>}>
          <div className="collab-card-list">{board.packages.map(r => <article className="collab-card" key={r.id}>
            <header><h3>需求 v{r.version} · {r.ownerName || '待确认客户联系人'}</h3>{status(r.status)}</header><p style={{whiteSpace: 'pre-wrap'}}>{r.summary}</p><p>约束：{r.constraints || '未登记'}</p>
            <p>证据：{r.attachments?.join('；') || '未登记'} ｜ 响应：{r.dueHint || '未登记'}</p>{r.changeReason && <p>变更原因：{r.changeReason}</p>}
            <div className="collab-scheme">方案依据：{r.schemeVersion ? `v${r.schemeVersion}` : '待回写'}<pre>{r.schemeNotes || '尚无当前版本方案'}</pre></div><footer>
              {workRole === 'market' && r.status === 'draft' && <Button onClick={() => edit('packages', r, '编辑需求草稿', [field('summary', '需求要点', 'textarea'), field('constraints', '约束', 'textarea', true)], {summary: r.summary, constraints: r.constraints})}>编辑草稿</Button>}
              {workRole === 'business' && r.status !== 'briefed' && <Button loading={busy} onClick={() => void run(`packages/${r.id}`, 'PATCH', {expectedRevision: r.revision, status: 'briefed'})}>确认发布 v{r.version}</Button>}
              {workRole === 'business' && r.status === 'briefed' && <Button onClick={() => edit('packages', r, '登记需求变更（下游需要复核）', [field('summary', '变更后的完整需求', 'textarea'), field('constraints', '变更后约束', 'textarea', true), field('changeReason', '变更原因及证据编号', 'textarea')], {summary: r.summary, constraints: r.constraints}, {status: 'changed'})}>登记变更</Button>}
              {workRole === 'design' && r.status === 'briefed' && <Button onClick={() => edit('packages', r, `回写 v${r.version} 方案`, [field('schemeNotes', '方案要点与核对依据', 'textarea')], {schemeNotes: r.schemeNotes})}>回写方案</Button>}
            </footer>{r.history?.length ? <details><summary>修改记录（修订 {r.revision}）</summary>{r.history.map((h, i) => <p key={i}>{stamp(h.at)} · {h.by} · {h.action} {h.detail}</p>)}</details> : null}
          </article>)}</div>{!board.packages.length && <EmptyState title="还没有需求" description="由市场录入第一条真实需求。"/>}</SectionCard>},
        {key: 'contracts', label: '设计采购契约', children: <SectionCard title="交付有依据，验收有结论" subtitle="设计提交证据；采购按质量规则确认或退回" action={workRole === 'design' && <Button type="primary" onClick={() => open({title: '建立设计采购契约', fields: [selectReq, field('name', '交付名称'), field('trigger', '触发条件'), field('deliverable', '交付物与编号要求'), field('qualityRule', '采购验收规则', 'textarea'), field('slaHours', '承诺时限（1～720 小时）', 'number'), field('designOwner', '设计责任人'), field('purchaseOwner', '采购责任人'), field('escalateTo', '超时升级给谁')], initial: {slaHours: 24}, submit: v => run('contracts', 'POST', v)})}>建立契约</Button>}>
          <div className="collab-card-list">{board.contracts.map(r => <article className="collab-card" key={r.id}><header><h3>{r.name} · 依据 v{r.basisVersion}</h3><Space>{status(r.status)}{r.needsReview && <Tag color="error">依据待复核</Tag>}{r.overdue && <Tag color="error">已超时</Tag>}</Space></header>
            <p>触发：{r.trigger} ｜ 交付：{r.deliverable}</p><p>验收规则：{r.qualityRule}</p><p>设计：{r.designOwner} → 采购：{r.purchaseOwner} ｜ 到期：{stamp(r.dueAt)} ｜ 升级：{r.escalateTo}</p><p>证据：{r.evidence || '未交付'} ｜ 说明：{r.note || '未登记'}</p>
            <footer>{workRole === 'design' && (r.status !== 'closed' || r.needsReview) && <Button onClick={() => contractAction(r, 'delivered')}>提交交付依据</Button>}
              {workRole === 'purchase' && r.status === 'delivered' && !r.needsReview && <><Button onClick={() => contractAction(r, 'closed')}>确认验收</Button><Button onClick={() => contractAction(r, 'returned')}>退回补齐</Button></>}</footer></article>)}</div>
          {!board.contracts.length && <EmptyState title="还没有交付契约" description="交底及方案确认后，建立交付和验收约定。"/>}</SectionCard>},
        {key: 'bom', label: '采购料表', children: <SectionCard title="版本与原系统凭证一起核对" subtitle="变更后先复核依据，保留已经发生的订单事实" action={workRole === 'design' && <Button type="primary" onClick={() => open({title: '登记设计料表', fields: [selectContract, field('materialCode', '物料编码（与原系统对应）'), field('materialName', '物料名称'), field('spec', '规格 / 图号'), field('qty', '数量（只填数字）'), field('unit', '单位'), field('needBy', '需用日期', 'date'), field('supplierHint', '供应商线索', undefined, true)], submit: v => run('bom', 'POST', v)})}>登记料表</Button>}>
          <Table<Bom> rowKey="id" dataSource={board.bom} scroll={{x: 1100}} columns={[
            {title: '物料', render: (_, r) => <><b>{r.materialCode} · {r.materialName}</b><div>{r.spec}</div><small>{r.qty} {r.unit} · 需用 {r.needBy}</small></>},
            {title: '依据', render: (_, r) => <>v{r.basisVersion} {r.needsReview && <Tag color="error">待复核</Tag>}</>},
            {title: '人工登记状态', render: (_, r) => <>{status(r.status)}<div>预计：{r.eta || '待确认'}</div></>}, {title: '核对记录', render: (_, r) => <>{r.note}<div>{r.sourceRef || '尚无原系统凭证'}</div></>},
            {title: '操作', width: 250, render: (_, r) => <Space wrap>{workRole === 'design' && r.needsReview && <Button onClick={() => edit('bom', r, '复核本行依据（不改变采购事实）', [field('note', '核对说明及变更差异', 'textarea')], {}, {rebase: true})}>设计复核</Button>}
              {workRole === 'purchase' && <><Button onClick={() => purchaseAction(r)}>交期 / 说明</Button><Select aria-label={`${r.materialName}采购操作`} placeholder="登记进度" style={{width: 120}} value={undefined}
                options={(r.needsReview ? ['blocked'] : ['quoted', 'ordered', 'arrived', 'blocked']).map(value => ({value, label: names[value]}))} onChange={value => purchaseAction(r, value)}/></>}</Space>},
          ]}/></SectionCard>},
        {key: 'decisions', label: '人工决策台账', children: <SectionCard title="决定、责任、期限、结果" subtitle="人工决定；完成时补充执行证据" action={workRole === 'project_manager' && <Button type="primary" onClick={() => open({title: '登记人工决策', fields: [field('title', '事项'), field('options', '讨论过的选项', 'textarea'), field('decision', '人工决定', 'textarea'), field('ownerName', '执行责任人'), field('dueAt', '完成期限', 'date'), field('evidence', '决策依据 / 会议编号')], submit: v => run('decisions', 'POST', {...v, projectId})})}>登记决策</Button>}>
          <Table<Decision> rowKey="id" dataSource={board.decisions} scroll={{x: 850}} columns={[{title: '事项 / 选项', render: (_, r) => <><b>{r.title}</b><div>{r.options}</div></>}, {title: '人工决定', dataIndex: 'decision'}, {title: '执行责任', render: (_, r) => <>{r.ownerName}<div>{r.dueAt}</div></>}, {title: '证据', dataIndex: 'evidence'},
            {title: '结果', render: (_, r) => r.status === 'closed' ? <>{r.result}<div>{r.resultEvidence}</div></> : workRole === 'project_manager' ? <Button onClick={() => edit('decisions', r, '登记执行结果', [field('result', '执行结果', 'textarea'), field('evidence', '执行证据编号')])}>登记结果</Button> : '待执行'}]}/></SectionCard>},
        {key: 'events', label: '变更记录', children: <SectionCard title="服务端操作记录" subtitle="完整记录随项目导出；成员授权由管理员单独管理"><Table<Event> rowKey="id" dataSource={board.events} scroll={{x: 800}} columns={[{title: '时间', dataIndex: 'at', render: stamp}, {title: '角色', dataIndex: 'role', render: v => labels[v as WorkRole] || v}, {title: '动作', dataIndex: 'action'}, {title: '说明', dataIndex: 'detail'}, {title: '记录编号', dataIndex: 'recordId'}]}/></SectionCard>},
        ...(access.admin ? [{key: 'members', label: '成员授权', children: <SectionCard title="本项目的业务权限" subtitle="管理员拥有全部权限；其他身份逐项目授权，撤销后立即失效" action={<Button onClick={() => authorize()}>新增 / 调整授权</Button>}><Table<Member> rowKey="id" dataSource={members} scroll={{x: 750}} columns={[{title: '姓名', dataIndex: 'name'}, {title: '浏览器身份编号', dataIndex: 'principal'}, {title: '允许角色', render: (_, r) => r.roles.map(x => labels[x]).join('、') || '已撤销'}, {title: '操作', render: (_, r) => <Button onClick={() => authorize(r)}>调整 / 撤销</Button>}]}/></SectionCard>}] : []),
      ]}/>
    </>}
    <Modal title={dialog?.title} open={Boolean(dialog)} confirmLoading={busy} onCancel={() => !busy && setDialog(null)} onOk={() => form.submit()} okText="保存" cancelText="取消">
      <Form form={form} layout="vertical" onFinish={async values => {
        // Include explicit empty text when editing so users can clear an optional field.
        const cleaned = Object.fromEntries(Object.entries(values).filter(([key, v]) => v !== undefined && !(v === '' && dialog?.fields.find(f => f.name === key)?.kind === 'date')));
        if (dialog && await dialog.submit(cleaned as Values)) setDialog(null);
      }}>{dialog?.fields.map(f => <Form.Item key={f.name} name={f.name} label={f.label} rules={f.optional ? [] : [{required: true, message: `请填写${f.label}`}]}>
        {f.kind === 'textarea' ? <Input.TextArea rows={4} maxLength={4000}/> : f.kind === 'number' ? <InputNumber min={1} max={720}/> : f.kind === 'select' || f.kind === 'roles' ? <Select showSearch optionFilterProp="label" mode={f.kind === 'roles' ? 'multiple' : undefined} options={f.kind === 'roles' ? roleOptions : f.options}/> : <Input type={f.kind === 'date' ? 'date' : 'text'}/>}
      </Form.Item>)}</Form><small>遇到版本冲突时，本次内容不会覆盖他人修改。请保留输入，关闭窗口核对最新记录后再提交。</small>
    </Modal>
  </div>;
}
