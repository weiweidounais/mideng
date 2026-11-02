import { useEffect, useMemo, useState } from 'react';
import { Alert, App as AntApp, Button, DatePicker, Descriptions, Drawer, Empty, Form, Input, Modal, Select, Space, Switch, Table, Tag, Timeline, Tooltip } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { AlertTriangle, ArrowRight, BellRing, CalendarClock, CheckCheck, ClipboardCheck, FileSpreadsheet, FileText, Link2, Plus, RefreshCw, Send, ShieldAlert, TimerReset, Truck } from 'lucide-react';
import type { ColumnsType } from 'antd/es/table';
import { PageTitle, SectionCard } from '../components/ui';
import { formatDateTime, isOverdue, overdueHours, useDemand } from '../demand/store';
import { bizRoleNames, contractStatusNames, deliverableStatusNames, type BizRole, type Contract, type ContractStatus, type DeliverableStatus } from '../demand/types';
import { ContractStatusTag, DeliverableTag, EmptyHint, RoleBar } from '../demand/components';
import './demand.css';

const canOperate = (role: BizRole) => role !== 'market';
const dueLabel = (contract: Contract) => {
  if (contract.status === 'done' || contract.deliverableStatus === 'received') return { text: '已关闭', danger: false };
  if (isOverdue(contract)) {
    const value = overdueHours(contract);
    return { text: value >= 24 ? `超时 ${Math.floor(value / 24)} 天 ${value % 24} 小时` : `超时 ${value} 小时`, danger: true };
  }
  const hours = Math.max(0, Math.ceil((new Date(contract.dueAt).getTime() - Date.now()) / 3600_000));
  return { text: hours >= 24 ? `剩余 ${Math.ceil(hours / 24)} 天` : `剩余 ${hours} 小时`, danger: false };
};

const contractTypeNames: Record<Contract['type'], string> = { bom: 'BOM / 料表', change: '变更通知', other: '其他交接' };
const typeOptions = (Object.keys(contractTypeNames) as Contract['type'][]).map((value) => ({ value, label: contractTypeNames[value] }));
const deliverableOptions = (Object.keys(deliverableStatusNames) as DeliverableStatus[]).map((value) => ({ value, label: deliverableStatusNames[value] }));
const statusOptions = (Object.keys(contractStatusNames) as ContractStatus[]).map((value) => ({ value, label: contractStatusNames[value] }));

export default function ContractsPage() {
  const { contracts, packages, role, createContract, updateContractStatus, updateDeliverable, urgeContract, focusContractId, setFocusContractId } = useDemand();
  const { message } = AntApp.useApp();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<'all' | ContractStatus>('all');
  const [type, setType] = useState<'all' | Contract['type']>('all');
  const [detailId, setDetailId] = useState('');
  const [creating, setCreating] = useState(false);
  const [statusFor, setStatusFor] = useState('');
  const [replyFor, setReplyFor] = useState('');
  const [form] = Form.useForm();
  const [statusForm] = Form.useForm();
  const [replyForm] = Form.useForm();

  useEffect(() => {
    if (!focusContractId) return;
    setDetailId(focusContractId);
    setFocusContractId('');
  }, [focusContractId, setFocusContractId]);

  const detail = contracts.find((item) => item.id === detailId);
  const projectName = (id: string) => packages.find((item) => item.id === id)?.projectName || '未关联需求包';
  const shown = useMemo(() => contracts.filter((item) => (status === 'all' || item.status === status) && (type === 'all' || item.type === type) && `${item.name}${item.code}${item.trigger}${item.owner}${projectName(item.packageId)}`.toLowerCase().includes(search.toLowerCase())), [contracts, packages, search, status, type]);
  const overdue = contracts.filter(isOverdue).length;
  const done = contracts.filter((item) => item.status === 'done').length;
  const openTodo = contracts.filter((item) => item.status !== 'done' && item.deliverableStatus !== 'received').sort((a, b) => Number(isOverdue(b)) - Number(isOverdue(a)) || new Date(a.dueAt).getTime() - new Date(b.dueAt).getTime());
  const pendingReply = contracts.filter((item) => item.lastUrgedAt && (!item.procurementReplyAt || new Date(item.procurementReplyAt).getTime() < new Date(item.lastUrgedAt).getTime())).length;

  function openCreate() {
    form.resetFields();
    form.setFieldsValue({ type: 'bom', status: 'active', urgent: false, dueAt: dayjs().add(1, 'day'), owner: '采购-王磊（接收）；设计-周航（提交）', consumer: '预制厂、采购部、项目经理' });
    setCreating(true);
  }

  async function saveContract() {
    let values: any;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const item = createContract({ ...values, dueAt: (values.dueAt as Dayjs).toISOString() });
    setCreating(false);
    setDetailId(item.id);
    message.success('接口契约已建立');
  }

  function openStatus(item: Contract) {
    statusForm.setFieldsValue({ status: item.status, note: '' });
    setStatusFor(item.id);
  }

  async function submitStatus() {
    let values: any;
    try {
      values = await statusForm.validateFields();
    } catch {
      return;
    }
    updateContractStatus(statusFor, values.status, values.note);
    setStatusFor('');
    message.success('契约状态已更新');
  }

  function openReply(item: Contract) {
    replyForm.setFieldsValue({
      deliverableStatus: item.deliverableStatus,
      promisedDelivery: item.promisedDelivery ? dayjs(item.promisedDelivery) : undefined,
      procurementReply: item.procurementReply || '',
    });
    setReplyFor(item.id);
  }

  async function submitReply() {
    let values: any;
    try {
      values = await replyForm.validateFields();
    } catch {
      return;
    }
    updateDeliverable(replyFor, {
      deliverableStatus: values.deliverableStatus,
      ...(values.promisedDelivery ? { promisedDelivery: (values.promisedDelivery as Dayjs).toISOString() } : {}),
      ...(values.procurementReply ? { procurementReply: values.procurementReply } : {}),
    });
    setReplyFor('');
    message.success('采购交付物已更新，契约台账同步');
  }

  const columns: ColumnsType<Contract> = [
    {
      title: '契约 / 交付物',
      dataIndex: 'name',
      width: 230,
      render: (_, item) => <button className="demand-table-main" onClick={() => setDetailId(item.id)}><strong>{item.name}</strong><small>{item.code} · {contractTypeNames[item.type]}</small></button>,
    },
    { title: '来源需求包', width: 190, render: (_, item) => <span className="demand-cell-stack">{projectName(item.packageId)}<small>{packages.find((pkg) => pkg.id === item.packageId)?.code || '—'}</small></span> },
    { title: '触发', dataIndex: 'trigger', width: 200, ellipsis: true },
    { title: '交付物', dataIndex: 'deliverable', width: 210, ellipsis: true },
    { title: '时限 / 超时', width: 142, render: (_, item) => { const due = dueLabel(item); return <span className={`demand-cell-stack ${due.danger ? 'demand-danger-text' : ''}`}><CalendarClock size={13} />{formatDateTime(item.dueAt)}<small className={due.danger ? 'demand-danger-text' : ''}>{due.text}</small></span>; } },
    { title: '质量', dataIndex: 'quality', width: 200, ellipsis: true },
    { title: '异常升级', dataIndex: 'escalation', width: 210, ellipsis: true },
    { title: 'Owner', dataIndex: 'owner', width: 180, ellipsis: true },
    { title: '状态', width: 132, render: (_, item) => <Space direction="vertical" size={3}><ContractStatusTag status={item.status} /><DeliverableTag status={item.deliverableStatus} /></Space> },
    { title: '', width: 72, render: (_, item) => <Button type="link" size="small" onClick={() => setDetailId(item.id)}>查看</Button> },
  ];

  return <div className="page-content demand-page">
    <PageTitle
      eyebrow="一期 · 设计↔采购接口"
      title="接口契约台账"
      description="BOM/料表交接先跑通：触发、交付物、时限、质量、异常升级、Owner 一处登记；采购以交付物为唯一待办来源。"
      actions={<Tooltip title={canOperate(role) ? '' : '请切换到设计、采购、项目经理或商务角色'}><Button type="primary" icon={<Plus size={16} />} disabled={!canOperate(role)} onClick={openCreate}>新建接口契约</Button></Tooltip>}
    />
    <RoleBar />
    <div className="demand-metrics">
      <div><span className="demand-metric-icon blue"><FileSpreadsheet size={18} /></span><div><small>执行中</small><strong>{contracts.filter((item) => item.status === 'active').length}</strong></div><p>含 BOM/料表与变更交接</p></div>
      <div><span className="demand-metric-icon red"><AlertTriangle size={18} /></span><div><small>已超时</small><strong>{overdue}</strong></div><p>按契约时限自动判定</p></div>
      <div><span className="demand-metric-icon orange"><BellRing size={18} /></span><div><small>催料未回</small><strong>{pendingReply}</strong></div><p>采购尚未给出新回复</p></div>
      <div><span className="demand-metric-icon green"><CheckCheck size={18} /></span><div><small>已完成</small><strong>{done}</strong></div><p>交付物已确认接收</p></div>
    </div>

    <SectionCard title={role === 'procurement' ? '采购待办（来自契约交付物）' : '采购交付物待办'} subtitle={role === 'procurement' ? '当前角色：采购 · 提交料表、登记交期或回复催料，不另建 Excel 台账' : '演示采购视角：待办直接来自契约交付物，可切换角色为采购体验'} action={<Tag bordered={false} color={role === 'procurement' ? 'blue' : 'default'}>{openTodo.length} 项待办</Tag>}>
      {openTodo.length ? <div className="demand-todo-list">{openTodo.slice(0, 5).map((item) => { const due = dueLabel(item); return <div className={`demand-todo ${due.danger ? 'danger' : ''}`} key={item.id}>
        <span className="demand-todo-icon"><Truck size={17} /></span>
        <div className="demand-todo-main"><strong>{item.name}</strong><small>{item.code} · {projectName(item.packageId)}</small><span><DeliverableTag status={item.deliverableStatus} /><em className={due.danger ? 'demand-danger-text' : ''}>{due.text}</em>{item.urgent && <Tag bordered={false} color="red">紧急</Tag>}</span></div>
        <div className="demand-todo-actions"><Button size="small" onClick={() => setDetailId(item.id)}>查看</Button>{role === 'procurement' && <Button size="small" type="primary" icon={<ClipboardCheck size={13} />} onClick={() => openReply(item)}>登记料表/交期</Button>}</div>
      </div>; })}</div> : <EmptyHint title="暂无采购交付物待办" description="所有契约交付物均已接收或关闭。" />}
    </SectionCard>

    <SectionCard title="契约台账" subtitle="字段对齐企划附录：触发、交付物、时限、质量、异常升级、Owner" action={<div className="demand-toolbar"><Input.Search allowClear placeholder="搜索契约、来源项目或 Owner" value={search} onChange={(event) => setSearch(event.target.value)} style={{ width: 260 }} /><Select value={type} onChange={setType} style={{ width: 140 }} options={[{ value: 'all', label: '全部类型' }, ...typeOptions]} /><Select value={status} onChange={setStatus} style={{ width: 128 }} options={[{ value: 'all', label: '全部状态' }, ...statusOptions]} /></div>}>
      <Table rowKey="id" columns={columns} dataSource={shown} pagination={false} scroll={{ x: 1720 }} className="demand-table" locale={{ emptyText: <Empty description="没有匹配的接口契约" /> }} />
    </SectionCard>
    <div className="demand-flow-hint"><ShieldAlert size={15} /><span>超时按“截止时间已过且交付物未接收/契约未完成”自动判定；变更通知作为事件类型保留，不做全公司变更大盘。</span></div>

    <Modal title="新建接口契约" open={creating} onCancel={() => setCreating(false)} onOk={() => void saveContract()} okText="建立契约" cancelText="取消" width={760} forceRender>
      <Alert type="info" showIcon message="主契约先做 BOM/料表交接；契约建立后即进入采购交付物待办。" style={{ marginBottom: 16 }} />
      <Form form={form} layout="vertical">
        <div className="demand-form-columns">
          <Form.Item name="name" label="契约名称" rules={[{ required: true, whitespace: true, message: '请输入契约名称' }]}><Input placeholder="如：BOM / 料表交接（管廊主体段）" maxLength={80} /></Form.Item>
          <Form.Item name="packageId" label="来源需求包" rules={[{ required: true, message: '请选择来源需求包' }]}><Select showSearch optionFilterProp="label" options={packages.map((item) => ({ value: item.id, label: `${item.code} · ${item.projectName}` }))} /></Form.Item>
        </div>
        <div className="demand-form-columns">
          <Form.Item name="type" label="契约类型"><Select options={typeOptions} /></Form.Item>
          <Form.Item name="dueAt" label="时限（截止时间）" rules={[{ required: true, message: '请选择截止时间' }]}><DatePicker showTime style={{ width: '100%' }} /></Form.Item>
        </div>
        <Form.Item name="trigger" label="触发条件" rules={[{ required: true, whitespace: true, message: '请填写触发条件' }]}><Input placeholder="如：设计完成施工段 BOM 自检并提交签字版料表" maxLength={160} /></Form.Item>
        <Form.Item name="deliverable" label="交付物" rules={[{ required: true, whitespace: true, message: '请填写交付物' }]}><Input placeholder="如：签字版 BOM + 分段料表（Excel/PDF）+ 变更说明" maxLength={160} /></Form.Item>
        <Form.Item name="quality" label="质量标准" rules={[{ required: true, whitespace: true, message: '请填写质量标准' }]}><Input.TextArea rows={2} placeholder="如：规格、数量、版本三对照；一次通过率 ≥85%" maxLength={240} /></Form.Item>
        <Form.Item name="escalation" label="异常升级" rules={[{ required: true, whitespace: true, message: '请填写异常升级规则' }]}><Input.TextArea rows={2} placeholder="如：超时 4 小时 → 采购经理；超时 1 天 → 项目经理" maxLength={240} /></Form.Item>
        <div className="demand-form-columns">
          <Form.Item name="owner" label="Owner" rules={[{ required: true, whitespace: true, message: '请填写 Owner' }]}><Input maxLength={120} /></Form.Item>
          <Form.Item name="consumer" label="交付物使用方" rules={[{ required: true, whitespace: true, message: '请填写使用方' }]}><Input maxLength={120} /></Form.Item>
        </div>
        <div className="demand-form-columns">
          <Form.Item name="status" label="初始状态"><Select options={statusOptions} /></Form.Item>
          <Form.Item name="urgent" label="标记紧急" valuePropName="checked"><Switch /></Form.Item>
        </div>
      </Form>
    </Modal>

    <Modal title="变更契约状态" open={Boolean(statusFor)} onCancel={() => setStatusFor('')} onOk={() => void submitStatus()} okText="保存状态" cancelText="取消" forceRender>
      <Form form={statusForm} layout="vertical">
        <Form.Item name="status" label="目标状态" rules={[{ required: true, message: '请选择目标状态' }]}><Select options={statusOptions} /></Form.Item>
        <Form.Item name="note" label="变更说明"><Input.TextArea rows={3} placeholder="说明阻塞、完成或重新打开的原因" maxLength={200} /></Form.Item>
      </Form>
    </Modal>

    <Modal title="登记料表 / 交期回复" open={Boolean(replyFor)} onCancel={() => setReplyFor('')} onOk={() => void submitReply()} okText="保存并同步台账" cancelText="取消" width={620} forceRender>
      <Alert type="info" showIcon message="采购在一次操作中更新交付物状态、承诺交期与回复；设计/项目经理看到同一台账。" style={{ marginBottom: 16 }} />
      <Form form={replyForm} layout="vertical">
        <Form.Item name="deliverableStatus" label="料表 / 交付物状态" rules={[{ required: true, message: '请选择交付物状态' }]}><Select options={deliverableOptions} /></Form.Item>
        <Form.Item name="promisedDelivery" label="承诺交期"><DatePicker showTime style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="procurementReply" label="采购回复"><Input.TextArea rows={4} placeholder="如：料表已按施工段拆分，首批清单已核对；请设计确认接口尺寸。" maxLength={400} showCount /></Form.Item>
      </Form>
    </Modal>

    <Drawer
      title={detail ? <div className="demand-drawer-title"><span>{detail.name}</span><small>{detail.code}</small></div> : '接口契约详情'}
      open={Boolean(detail)}
      onClose={() => setDetailId('')}
      width={760}
      extra={detail && <Space wrap>
        <Button icon={<RefreshCw size={14} />} onClick={() => openStatus(detail)}>变更状态</Button>
        {role === 'procurement' && <Button type="primary" icon={<ClipboardCheck size={14} />} onClick={() => openReply(detail)}>登记料表/交期</Button>}
        {role !== 'procurement' && detail.status !== 'done' && <Button icon={<BellRing size={14} />} onClick={() => { urgeContract(detail.id, '已催采购回复料表与交期。'); message.success('已记录催料'); }}>催料</Button>}
      </Space>}
    >
      {detail && <ContractDetail item={detail} projectName={projectName(detail.packageId)} onStatus={() => openStatus(detail)} onReply={() => openReply(detail)} onUrge={() => { urgeContract(detail.id, '已催采购回复料表与交期。'); message.success('已记录催料'); }} />}
    </Drawer>
  </div>;
}

function ContractDetail({ item, projectName, onStatus, onReply, onUrge }: { item: Contract; projectName: string; onStatus: () => void; onReply: () => void; onUrge: () => void }) {
  const { role } = useDemand();
  const due = dueLabel(item);
  return <div className="demand-detail">
    <div className="demand-detail-top"><div><ContractStatusTag status={item.status} /><DeliverableTag status={item.deliverableStatus} />{item.urgent && <Tag bordered={false} color="red">紧急</Tag>}</div><span className={`demand-muted ${due.danger ? 'demand-danger-text' : ''}`}>{due.text} · 更新于 {formatDateTime(item.updatedAt)}</span></div>
    <Alert type={due.danger ? 'error' : item.status === 'done' ? 'success' : 'info'} showIcon message={due.danger ? `契约已超时：${formatDateTime(item.dueAt)} 截止` : item.status === 'done' ? '契约已完成，交付物已接收' : `契约执行中，截止 ${formatDateTime(item.dueAt)}`} description={due.danger ? `已超时约 ${overdueHours(item)} 小时，按异常升级规则处理：${item.escalation}` : '设计提交、采购接收共用同一台账；采购回复会同步到例外页。'} style={{ marginBottom: 18 }} />
    <SectionCard title="契约字段" subtitle="一期只做设计↔采购接口契约，不扩成全公司变更大盘" className="demand-detail-card">
      <Descriptions column={1} size="small" bordered items={[
        { key: 'project', label: '来源需求包', children: projectName },
        { key: 'type', label: '契约类型', children: contractTypeNames[item.type] },
        { key: 'trigger', label: '触发', children: item.trigger },
        { key: 'deliverable', label: '交付物', children: item.deliverable },
        { key: 'due', label: '时限', children: `${formatDateTime(item.dueAt)}（${due.text}）` },
        { key: 'quality', label: '质量', children: item.quality },
        { key: 'escalation', label: '异常升级', children: item.escalation },
        { key: 'owner', label: 'Owner', children: item.owner },
        { key: 'consumer', label: '使用方', children: item.consumer },
      ]} />
    </SectionCard>
    <SectionCard title="采购交付物 / 交期" subtitle="采购侧的待办唯一来源" className="demand-detail-card">
      <div className="demand-procurement-panel">
        <div><span>料表 / 交付物</span><DeliverableTag status={item.deliverableStatus} /></div>
        <div><span>承诺交期</span><strong>{formatDateTime(item.promisedDelivery)}</strong></div>
        <div><span>最近催料</span><strong>{formatDateTime(item.lastUrgedAt)}</strong></div>
        <div><span>采购回复时间</span><strong>{formatDateTime(item.procurementReplyAt)}</strong></div>
        <div className="wide"><span>采购回复</span><p>{item.procurementReply || '采购尚未回复。'}</p></div>
      </div>
      <Space wrap style={{ marginTop: 16 }}>
        {role === 'procurement' ? <Button type="primary" icon={<ClipboardCheck size={14} />} onClick={onReply}>登记料表 / 交期回复</Button> : <Button icon={<BellRing size={14} />} disabled={item.status === 'done'} onClick={onUrge}>催料并记录</Button>}
        <Button icon={<RefreshCw size={14} />} onClick={onStatus}>变更契约状态</Button>
      </Space>
    </SectionCard>
    <SectionCard title="契约痕迹" subtitle="状态、催料与采购回复均留痕" className="demand-detail-card">
      <Timeline items={item.history.map((event) => ({
        color: event.action.includes('催料') ? 'red' : event.action.includes('完成') ? 'green' : event.action.includes('创建') ? 'blue' : 'gray',
        children: <div className="demand-history-item"><div><Tag bordered={false}>{event.action}</Tag><span>{bizRoleNames[event.role]} · {event.by} · {formatDateTime(event.at)}</span></div><p>{event.note}</p>{event.from && event.to && <small className="demand-muted">{event.from} → {event.to}</small>}</div>,
      }))} />
    </SectionCard>
  </div>;
}
