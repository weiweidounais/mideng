import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Drawer, Empty, Form, Input, Modal, Select, Space, Table, Tag, Timeline, Tooltip } from 'antd';
import { AlertTriangle, ArrowRight, BriefcaseBusiness, CalendarClock, CheckCircle2, ClipboardList, FileText, GitCompareArrows, Link2, MessageSquareText, Pencil, Plus, RefreshCw, Send, Sparkles, Trash2 } from 'lucide-react';
import type { ColumnsType } from 'antd/es/table';
import { useApp } from '../store';
import { PageTitle, SectionCard } from '../components/ui';
import { useDemand, formatDateTime } from '../demand/store';
import { bizRolePeople, packageStatusNames, type Attachment, type BizRole, type PackageStatus, type RequirementPackage } from '../demand/types';
import { EmptyHint, PackageStatusTag, RoleBar } from '../demand/components';
import './demand.css';

const canWrite = (role: BizRole) => role === 'market' || role === 'commercial';
const canPublish = (role: BizRole) => role === 'commercial';
const canSolution = (role: BizRole) => role === 'design' || role === 'commercial';

const solutionState = (item: RequirementPackage) => {
  if (!item.solution) return { label: '未回写', color: 'default', conflict: false };
  if (item.solution.version < item.version) return { label: `需复核 v${item.solution.version}`, color: 'red', conflict: true };
  return { label: `已回写 v${item.solution.version}`, color: 'green', conflict: false };
};

const attachmentKindOptions = ['pdf', 'docx', 'xlsx', 'dwg', 'png', 'jpg', 'other'].map((value) => ({ value, label: value.toUpperCase() }));

export default function RequirementsPage() {
  const { packages, contracts, role, createPackage, updatePackage, publishPackage, addSolution, focusPackageId, setFocusPackageId, setFocusContractId } = useDemand();
  const { navigate } = useApp();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<'all' | PackageStatus>('all');
  const [detailId, setDetailId] = useState('');
  const [editing, setEditing] = useState<string | null | undefined>(undefined);
  const [publishing, setPublishing] = useState('');
  const [solutionFor, setSolutionFor] = useState('');
  const [form] = Form.useForm();
  const [publishForm] = Form.useForm();
  const [solutionForm] = Form.useForm();

  useEffect(() => {
    if (!focusPackageId) return;
    setDetailId(focusPackageId);
    setFocusPackageId('');
  }, [focusPackageId, setFocusPackageId]);

  const detail = packages.find((item) => item.id === detailId);
  const shown = useMemo(() => packages.filter((item) => (status === 'all' || item.status === status) && `${item.projectName}${item.code}${item.clientName}${item.summary}`.toLowerCase().includes(search.toLowerCase())), [packages, search, status]);
  const conflicts = packages.filter((item) => item.solution && item.solution.version < item.version).length;
  const drafted = packages.filter((item) => item.status === 'draft').length;
  const briefed = packages.filter((item) => item.status !== 'draft').length;

  function openCreate() {
    form.resetFields();
    form.setFieldsValue({ marketOwner: bizRolePeople.market, attachments: [{ name: '', kind: 'pdf', note: '' }] });
    setEditing(null);
  }

  function openEdit(item: RequirementPackage) {
    form.setFieldsValue({ ...item, changeNote: '', attachments: item.attachments.length ? item.attachments : [{ name: '', kind: 'pdf', note: '' }] });
    setEditing(item.id);
  }

  async function savePackage() {
    let values: any;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const input = {
      projectName: values.projectName,
      clientName: values.clientName,
      marketOwner: values.marketOwner,
      summary: values.summary,
      schedule: values.schedule,
      budget: values.budget,
      technical: values.technical,
      attachments: (values.attachments || []).filter((file: Attachment) => file?.name?.trim()).map((file: Attachment) => ({ ...file, id: file.id || '' })),
    };
    if (editing === null) {
      const item = createPackage(input);
      setEditing(undefined);
      setDetailId(item.id);
    } else if (typeof editing === 'string') {
      updatePackage(editing, input, values.changeNote);
      setEditing(undefined);
    }
  }

  function openPublish(item: RequirementPackage) {
    publishForm.setFieldsValue({ note: item.status === 'draft' ? '确认需求包口径，向设计/采购/项目经理发布交底。' : '按最新需求版本重新交底，并通知设计复核方案。' });
    setPublishing(item.id);
  }

  async function submitPublish() {
    let values: any;
    try {
      values = await publishForm.validateFields();
    } catch {
      return;
    }
    publishPackage(publishing, values.note);
    setPublishing('');
  }

  function openSolution(item: RequirementPackage) {
    solutionForm.setFieldsValue(item.solution ? { content: item.solution.content, optimization: item.solution.optimization, risks: item.solution.risks } : { content: '', optimization: '', risks: '' });
    setSolutionFor(item.id);
  }

  async function submitSolution() {
    let values: any;
    try {
      values = await solutionForm.validateFields();
    } catch {
      return;
    }
    addSolution(solutionFor, values);
    setSolutionFor('');
  }

  const columns: ColumnsType<RequirementPackage> = [
    {
      title: '项目 / 需求包',
      dataIndex: 'projectName',
      render: (_, item) => <button className="demand-table-main" onClick={() => setDetailId(item.id)}><strong>{item.projectName}</strong><small>{item.code} · {item.clientName}</small></button>,
    },
    { title: '状态', dataIndex: 'status', width: 120, render: (_, item) => <PackageStatusTag status={item.status} version={item.version} /> },
    { title: '业主要点', dataIndex: 'summary', ellipsis: true, render: (value: string) => <span className="demand-ellipsis">{value}</span> },
    { title: '方案回写', width: 130, render: (_, item) => { const state = solutionState(item); return <Tag bordered={false} color={state.color}>{state.label}</Tag>; } },
    { title: '交底', width: 120, render: (_, item) => item.briefedAt ? <span className="demand-cell-stack">已交底<small>{formatDateTime(item.briefedAt)}</small></span> : <span className="demand-muted">未交底</span> },
    { title: '更新', dataIndex: 'updatedAt', width: 120, render: (value: string) => <span className="demand-muted">{formatDateTime(value)}</span> },
    { title: '', width: 74, render: (_, item) => <Button type="link" size="small" onClick={() => setDetailId(item.id)}>查看</Button> },
  ];

  return <div className="page-content demand-page">
    <PageTitle
      eyebrow="一期 · 甲方需求入口"
      title="需求交底包"
      description="市场录入甲方需求，商务发布交底；设计、采购、项目经理看到同一版本，变更有痕迹。"
      actions={<Space><Tooltip title={canWrite(role) ? '' : '请切换到市场或商务角色录入'}><Button type="primary" icon={<Plus size={16} />} disabled={!canWrite(role)} onClick={openCreate}>录入甲方需求</Button></Tooltip></Space>}
    />
    <RoleBar />
    <div className="demand-metrics">
      <div><span className="demand-metric-icon violet"><ClipboardList size={18} /></span><div><small>需求包</small><strong>{packages.length}</strong></div><p>同一事实源</p></div>
      <div><span className="demand-metric-icon green"><CheckCircle2 size={18} /></span><div><small>已交底</small><strong>{briefed}</strong></div><p>设计/采购/项目经理可见</p></div>
      <div><span className="demand-metric-icon orange"><Send size={18} /></span><div><small>待交底</small><strong>{drafted}</strong></div><p>草稿状态需求包</p></div>
      <div><span className="demand-metric-icon red"><GitCompareArrows size={18} /></span><div><small>版本冲突</small><strong>{conflicts}</strong></div><p>方案版本落后于需求包</p></div>
    </div>
    <SectionCard title="需求包列表" subtitle="一份需求包只维护一个对内版本；交底后修改会自动标记为有变更" action={<div className="demand-toolbar"><Input.Search allowClear placeholder="搜索项目、需求包或业主" value={search} onChange={(event) => setSearch(event.target.value)} style={{ width: 260 }} /><Select value={status} onChange={setStatus} style={{ width: 128 }} options={[{ value: 'all', label: '全部状态' }, ...(Object.keys(packageStatusNames) as PackageStatus[]).map((value) => ({ value, label: packageStatusNames[value] }))]} /></div>}>
      <Table rowKey="id" columns={columns} dataSource={shown} pagination={false} scroll={{ x: 980 }} className="demand-table" locale={{ emptyText: <Empty description="没有匹配的需求包" /> }} />
    </SectionCard>
    <div className="demand-flow-hint"><Sparkles size={15} /><span>演示链路：市场录入 → 商务交底 → 设计回写方案 → 商务/市场对甲方沟通 → 设计↔采购 BOM 契约 → 项目经理例外页。</span></div>

    <PackageForm open={editing !== undefined} editing={editing} form={form} onCancel={() => setEditing(undefined)} onSave={() => void savePackage()} />

    <Modal title="发布交底" open={Boolean(publishing)} onCancel={() => setPublishing('')} onOk={() => void submitPublish()} okText="确认交底" cancelText="取消" forceRender>
      <Alert type="info" showIcon message="交底后设计、采购、项目经理看到同一版本；后续需求修改将标记为“有变更”。" style={{ marginBottom: 16 }} />
      <Form form={publishForm} layout="vertical"><Form.Item name="note" label="交底说明" rules={[{ required: true, message: '请填写交底说明' }]}><Input.TextArea rows={3} maxLength={200} showCount /></Form.Item></Form>
    </Modal>

    <Modal title="回写方案优化要点" open={Boolean(solutionFor)} onCancel={() => setSolutionFor('')} onOk={() => void submitSolution()} okText="保存回写" cancelText="取消" width={640} forceRender>
      <Alert type="info" showIcon message="方案回写按当前需求包版本记录；市场/商务可据此向甲方反馈，项目经理可在例外页查看断点。" style={{ marginBottom: 16 }} />
      <Form form={solutionForm} layout="vertical">
        <Form.Item name="content" label="方案要点" rules={[{ required: true, message: '请填写方案要点' }]}><Input.TextArea rows={4} placeholder="按施工段说明方案组织、关键做法与 BOM 拆分方式" maxLength={600} showCount /></Form.Item>
        <Form.Item name="optimization" label="优化建议" rules={[{ required: true, message: '请填写优化建议' }]}><Input.TextArea rows={3} placeholder="可量化的优化点、预计收益或需业主确认的事项" maxLength={400} showCount /></Form.Item>
        <Form.Item name="risks" label="风险与前提"><Input.TextArea rows={3} placeholder="技术、供货或业主确认前提" maxLength={400} showCount /></Form.Item>
      </Form>
    </Modal>

    <Drawer
      title={detail ? <div className="demand-drawer-title"><span>{detail.projectName}</span><small>{detail.code}</small></div> : '需求包详情'}
      open={Boolean(detail)}
      onClose={() => setDetailId('')}
      width={780}
      extra={detail && <Space wrap>
        {canWrite(role) && <Button icon={<Pencil size={14} />} onClick={() => openEdit(detail)}>编辑需求</Button>}
        {canPublish(role) && <Button type="primary" icon={<Send size={14} />} onClick={() => openPublish(detail)}>{detail.status === 'draft' ? '确认交底' : '重新交底'}</Button>}
        {canSolution(role) && <Button type="primary" ghost icon={<Sparkles size={14} />} onClick={() => openSolution(detail)}>{detail.solution ? '更新方案回写' : '回写方案'}</Button>}
      </Space>}
    >
      {detail && <PackageDetail item={detail} contracts={contracts} onOpenContract={(id) => { setFocusContractId(id); navigate('contracts'); }} />}
    </Drawer>
  </div>;
}

function PackageDetail({ item, contracts, onOpenContract }: { item: RequirementPackage; contracts: ReturnType<typeof useDemand>['contracts']; onOpenContract: (id: string) => void }) {
  const state = solutionState(item);
  const related = contracts.filter((contract) => contract.packageId === item.id);
  return <div className="demand-detail">
    <div className="demand-detail-top">
      <div><PackageStatusTag status={item.status} version={item.version} /><Tag bordered={false}>{item.clientName}</Tag><Tag bordered={false}>市场：{item.marketOwner}</Tag></div>
      <span className="demand-muted">更新于 {formatDateTime(item.updatedAt)}</span>
    </div>
    <Alert
      type={state.conflict ? 'error' : state.color === 'green' ? 'success' : 'warning'}
      showIcon
      message={state.conflict ? `方案基于 v${item.solution?.version}，需求包已到 v${item.version}` : state.color === 'green' ? `方案已按 v${item.solution?.version} 回写` : '设计尚未回写方案要点'}
      description={state.conflict ? '市场/商务对甲方沟通前需设计确认口径；项目经理已在例外页看到版本冲突。' : state.color === 'green' ? '市场/商务可直接引用该方案要点向甲方反馈。' : '需求已交底，但设计侧还没有形成可对甲方沟通的方案要点。'}
      style={{ marginBottom: 18 }}
    />
    <SectionCard title="甲方需求" subtitle="市场录入的结构化需求与附件索引" className="demand-detail-card">
      <div className="demand-requirement-grid">
        <div><span><BriefcaseBusiness size={14} />业主要点</span><p>{item.summary}</p></div>
        <div><span><CalendarClock size={14} />工期约束</span><p>{item.schedule}</p></div>
        <div><span><FileText size={14} />造价约束</span><p>{item.budget}</p></div>
        <div><span><AlertTriangle size={14} />技术约束</span><p>{item.technical}</p></div>
      </div>
      <div className="demand-attachments"><strong><Link2 size={14} />附件索引</strong>{item.attachments.length ? <div>{item.attachments.map((file) => <span key={file.id} className="demand-attachment"><FileText size={13} /><b>{file.name}</b><small>{file.kind.toUpperCase()}{file.note ? ` · ${file.note}` : ''}</small></span>)}</div> : <Empty description="暂无附件索引" image={Empty.PRESENTED_IMAGE_SIMPLE} />}</div>
    </SectionCard>
    <SectionCard title="方案优化回写" subtitle="设计可会同商务回写，市场/商务可见" className="demand-detail-card">
      {item.solution ? <div className="demand-solution">
        <div className="demand-solution-meta"><Tag bordered={false} color="purple">v{item.solution.version} 方案</Tag><span>{item.solution.by} · {formatDateTime(item.solution.at)}</span></div>
        <div><strong>方案要点</strong><p>{item.solution.content}</p></div>
        <div><strong>优化建议</strong><p>{item.solution.optimization}</p></div>
        {item.solution.risks && <div><strong>风险与前提</strong><p>{item.solution.risks}</p></div>}
      </div> : <EmptyHint title="方案还未回写" description="设计回写后，这里会显示方案要点与优化建议，并同步给市场/商务。" />}
    </SectionCard>
    <SectionCard title="关联接口契约" subtitle="以需求包为来源的 BOM/料表或变更交接" className="demand-detail-card">
      {related.length ? <div className="demand-related-contracts">{related.map((contract) => <button key={contract.id} onClick={() => onOpenContract(contract.id)}><span><strong>{contract.name}</strong><small>{contract.code} · {contract.owner}</small></span><Tag bordered={false} color={contract.status === 'done' ? 'green' : contract.status === 'blocked' ? 'red' : 'blue'}>{contract.status === 'done' ? '已完成' : contract.status === 'blocked' ? '已阻塞' : '执行中'}</Tag><ArrowRight size={14} /></button>)}</div> : <EmptyHint title="暂无关联契约" description="设计可在接口契约台账中为本需求包建立 BOM/料表交接。" />}
    </SectionCard>
    <SectionCard title="版本与变更痕迹" subtitle="每次编辑、交底与方案回写均留痕" className="demand-detail-card">
      <Timeline items={item.history.map((entry) => ({
        color: entry.action === 'solution' ? 'purple' : entry.action === 'updated' ? 'orange' : entry.action === 'briefed' ? 'green' : 'blue',
        children: <div className="demand-history-item"><div><Tag bordered={false}>{entry.action === 'created' ? '录入' : entry.action === 'briefed' ? '交底' : entry.action === 'updated' ? '变更' : '方案回写'}</Tag><strong>v{entry.version}</strong><span>{entry.by} · {formatDateTime(entry.at)}</span></div><p>{entry.note}</p>{entry.changes.length > 0 && <ul>{entry.changes.map((change) => <li key={change}>{change}</li>)}</ul>}</div>,
      }))} />
    </SectionCard>
  </div>;
}

function PackageForm({ open, editing, form, onCancel, onSave }: { open: boolean; editing: string | null | undefined; form: ReturnType<typeof Form.useForm>[0]; onCancel: () => void; onSave: () => void }) {
  const isEdit = typeof editing === 'string';
  return <Modal title={isEdit ? '编辑需求包' : '录入甲方需求'} open={open} onCancel={onCancel} onOk={onSave} okText={isEdit ? '保存并标记变更' : '保存为草稿'} cancelText="取消" width={760} forceRender>
    <Alert type="info" showIcon message={isEdit ? '保存后需求包版本自动加一；已交底的需求包会标记为“有变更”。' : '先保存为草稿，由商务确认后发布交底。'} style={{ marginBottom: 16 }} />
    <Form form={form} layout="vertical">
      <div className="demand-form-columns">
        <Form.Item name="projectName" label="项目名称" rules={[{ required: true, whitespace: true, message: '请输入项目名称' }]}><Input placeholder="如：咸阳高新区综合管廊一期" maxLength={60} /></Form.Item>
        <Form.Item name="clientName" label="业主 / 甲方" rules={[{ required: true, whitespace: true, message: '请输入业主名称' }]}><Input placeholder="如：咸阳高新区建设开发有限公司" maxLength={60} /></Form.Item>
      </div>
      <div className="demand-form-columns">
        <Form.Item name="marketOwner" label="市场负责人" rules={[{ required: true, message: '请选择市场负责人' }]}><Select options={['李婉', '张琪'].map((value) => ({ value, label: value }))} /></Form.Item>
        <Form.Item name="changeNote" label={isEdit ? '变更说明（必填）' : '备注'} rules={isEdit ? [{ required: true, whitespace: true, message: '请说明本次变更' }] : []}><Input placeholder="如：业主调整首批供货节点" maxLength={100} /></Form.Item>
      </div>
      <Form.Item name="summary" label="业主要点" rules={[{ required: true, whitespace: true, message: '请填写业主要点' }]}><Input.TextArea rows={3} placeholder="业主最关心的目标、节点、沟通机制与验收要求" maxLength={500} showCount /></Form.Item>
      <Form.Item name="schedule" label="工期约束" rules={[{ required: true, whitespace: true, message: '请填写工期约束' }]}><Input.TextArea rows={2} placeholder="关键节点与交付时间" maxLength={300} /></Form.Item>
      <Form.Item name="budget" label="造价约束" rules={[{ required: true, whitespace: true, message: '请填写造价约束' }]}><Input.TextArea rows={2} placeholder="概算/合同额、控制线与变更费用要求" maxLength={300} /></Form.Item>
      <Form.Item name="technical" label="技术约束" rules={[{ required: true, whitespace: true, message: '请填写技术约束' }]}><Input.TextArea rows={2} placeholder="执行标准、关键参数、特殊工艺与检测要求" maxLength={400} /></Form.Item>
      <Form.List name="attachments">{(fields, { add, remove }) => <div className="demand-attachment-form"><div className="demand-attachment-form-head"><strong>附件索引</strong><Button size="small" icon={<Plus size={13} />} onClick={() => add({ name: '', kind: 'pdf', note: '' })}>添加附件</Button></div>{fields.map((field) => <div className="demand-attachment-row" key={field.key}><Form.Item name={[field.name, 'name']} noStyle><Input placeholder="附件名称，如：业主需求确认单.pdf" /></Form.Item><Form.Item name={[field.name, 'kind']} noStyle><Select options={attachmentKindOptions} style={{ width: 92 }} /></Form.Item><Form.Item name={[field.name, 'note']} noStyle><Input placeholder="备注，如：签字版 / 含图纸" /></Form.Item><Form.Item name={[field.name, 'id']} hidden><Input /></Form.Item><Button type="text" danger icon={<Trash2 size={14} />} onClick={() => remove(field.name)} aria-label="删除附件" /></div>)}{!fields.length && <p className="demand-muted">暂无附件索引，可稍后补充。</p>}</div>}</Form.List>
    </Form>
  </Modal>;
}
