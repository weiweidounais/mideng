import {useCallback, useEffect, useMemo, useState} from 'react';
import {Alert, Button, Form, Input, Modal, Select, Space, Switch, Table, Tabs, Tag, Timeline, message} from 'antd';
import {AlertTriangle, ClipboardList, FileStack, PackageSearch, RefreshCw, Send} from 'lucide-react';
import {api, json} from '../api';
import {EmptyState, PageTitle, SectionCard} from '../components/ui';
import './collaboration.css';

type WorkRole = '市场' | '商务' | '项目经理' | '设计' | '采购';
type Board = {
  packages: any[];
  contracts: any[];
  bom: any[];
  exceptions: any[];
};

const roles: WorkRole[] = ['市场', '商务', '项目经理', '设计', '采购'];
const statusColor: Record<string, string> = {
  draft: 'default', briefed: 'processing', changed: 'warning',
  open: 'default', in_progress: 'processing', delivered: 'success', overdue: 'error', closed: 'default',
  pending: 'default', quoted: 'processing', ordered: 'success', arrived: 'success', blocked: 'error',
  high: 'error', medium: 'warning', low: 'default',
};
const statusLabel: Record<string, string> = {
  draft: '草稿', briefed: '已交底', changed: '有变更',
  open: '待处理', in_progress: '推进中', delivered: '已交付', overdue: '已超时', closed: '关闭',
  pending: '待办', quoted: '已询价', ordered: '已下单', arrived: '已到货', blocked: '阻塞',
};

export default function CollaborationPage() {
  const [board, setBoard] = useState<Board>({packages: [], contracts: [], bom: [], exceptions: []});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [workRole, setWorkRole] = useState<WorkRole>(() => (localStorage.getItem('zhixu-work-role') as WorkRole) || '项目经理');
  const [mineOnly, setMineOnly] = useState(() => {
    const saved = localStorage.getItem('zhixu-collab-mine');
    if (saved === '0' || saved === '1') return saved === '1';
    return (localStorage.getItem('zhixu-work-role') || '项目经理') === '项目经理';
  });
  const [tab, setTab] = useState(() => {
    const h = location.hash.split('/')[1];
    if (h === 'requirements') return 'packages';
    if (h === 'contracts') return 'contracts';
    if (h === 'exceptions') return 'exceptions';
    return 'exceptions';
  });
  const [reqOpen, setReqOpen] = useState(false);
  const [schemeOpen, setSchemeOpen] = useState<any>(null);
  const [ifaceOpen, setIfaceOpen] = useState(false);
  const [bomOpen, setBomOpen] = useState(false);
  const [reqForm] = Form.useForm();
  const [schemeForm] = Form.useForm();
  const [ifaceForm] = Form.useForm();
  const [bomForm] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<Board>('/collaboration/board');
      setBoard(data);
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { localStorage.setItem('zhixu-work-role', workRole); }, [workRole]);
  useEffect(() => { localStorage.setItem('zhixu-collab-mine', mineOnly ? '1' : '0'); }, [mineOnly]);

  const mutate = async (path: string, options: RequestInit) => {
    setBusy(path);
    try {
      await api(path, options);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : '操作失败');
      throw e;
    } finally {
      setBusy('');
    }
  };

  const createReq = async () => {
    const values = await reqForm.validateFields();
    await mutate('/collaboration/packages', json('POST', {
      ...values,
      marketOwner: workRole.startsWith('市场') ? workRole : '市场',
      attachments: (values.attachments || '').split(/[,，\n]/).map((s: string) => s.trim()).filter(Boolean),
    }));
    setReqOpen(false);
    reqForm.resetFields();
    setTab('packages');
  };

  const brief = (row: any) => mutate(`/collaboration/packages/${row.id}`, json('PATCH', {status: 'briefed'}));
  const markChanged = (row: any) => mutate(`/collaboration/packages/${row.id}`, json('PATCH', {status: 'changed'}));
  const saveScheme = async () => {
    const values = await schemeForm.validateFields();
    await mutate(`/collaboration/packages/${schemeOpen.id}`, json('PATCH', {
      schemeNotes: values.schemeNotes,
      schemeAuthor: workRole,
    }));
    setSchemeOpen(null);
    schemeForm.resetFields();
  };

  const createIface = async () => {
    const values = await ifaceForm.validateFields();
    await mutate('/collaboration/contracts', json('POST', values));
    setIfaceOpen(false);
    ifaceForm.resetFields();
    setTab('contracts');
  };

  const createBom = async () => {
    const values = await bomForm.validateFields();
    await mutate('/collaboration/bom', json('POST', values));
    setBomOpen(false);
    bomForm.resetFields();
    setTab('bom');
  };

  const hint = useMemo(() => ({
    '市场': '录入甲方需求要点与附件索引，少因内部不同步反复改方案。',
    '商务': '确认并发布交底包，查看设计方案回写。',
    '项目经理': '看例外/待办一页，少开对接会。',
    '设计': '看同版本需求包，回写方案要点，维护 BOM 契约。',
    '采购': '看待交料表与交期，少催、少另建 Excel。',
  }[workRole]), [workRole]);


  const exceptionsForRole = useMemo(() => {
    if (!mineOnly) return board.exceptions;
    if (workRole === '项目经理') return board.exceptions; // 一页纸看全量断点
    return board.exceptions.filter(e => {
      const owner = String(e.owner || '');
      const typ = String(e.type || '');
      if (workRole === '市场') return typ.includes('需求') || owner.includes('市场') || owner.includes('商务');
      if (workRole === '商务') return typ.includes('需求') || typ.includes('方案') || owner.includes('商务');
      if (workRole === '设计') return typ.includes('方案') || typ.includes('料表') || owner.includes('设计');
      if (workRole === '采购') return typ.includes('催料') || typ.includes('料表') || owner.includes('采购');
      return true;
    });
  }, [board.exceptions, mineOnly, workRole]);

  return (
    <div className="collab-page page-content">
      <PageTitle
        eyebrow="COLLABORATION · PHASE 1"
        title="协同工作台 · 沟通成本"
        description="甲方需求交底 → 同版本同步 → 方案回写 → 设计↔采购契约 → 例外一页看全。"
        actions={
          <Space wrap>
            <Select
              aria-label="工作角色"
              value={workRole}
              style={{width: 140}}
              options={roles.map(r => ({value: r, label: r}))}
              onChange={setWorkRole}
            />
            <Button icon={<RefreshCw size={15}/>} onClick={() => void load()} loading={loading}>刷新</Button>
          </Space>
        }
      />

      <Alert className="collab-role-hint" type="info" showIcon message={`当前工作角色：${workRole} · 服务端同版本`} description={`${hint} 数据在服务端，换浏览器也能看见同一份。`}/>
      {error && <Alert type="error" showIcon closable message={error} onClose={() => setError('')} style={{marginBottom: 16}}/>}

      <div className="collab-metrics">
        <div><b>{exceptionsForRole.length}</b><span>例外待办</span></div>
        <div><b>{board.packages.filter(p => p.status === 'draft').length}</b><span>未交底需求</span></div>
        <div><b>{board.contracts.filter(c => c.status === 'overdue').length}</b><span>超时契约</span></div>
        <div><b>{board.bom.filter(b => b.status === 'blocked' || b.status === 'pending').length}</b><span>采购待办</span></div>
      </div>

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'exceptions',
            label: <span><AlertTriangle size={14}/> 例外/待办</span>,
            children: (
              <SectionCard title="例外一页纸" subtitle="默认按当前工作角色过滤；项目经理看全量断点"
                action={<Space><span className="muted">只看与我相关</span><Switch checked={mineOnly} onChange={setMineOnly} /></Space>}>
                {loading ? <div role="status">加载中…</div> : exceptionsForRole.length ? (
                  <Table
                    rowKey="id"
                    pagination={false}
                    dataSource={exceptionsForRole}
                    columns={[
                      {title: '类型', dataIndex: 'type', width: 120, render: (t, r) => <Tag color={statusColor[r.severity]}>{t}</Tag>},
                      {title: '项目', dataIndex: 'projectName', width: 200},
                      {title: '说明', dataIndex: 'title'},
                      {title: '责任人', dataIndex: 'owner', width: 120},
                    ]}
                  />
                ) : <EmptyState icon={<AlertTriangle/>} title="暂无例外" description="演示链跑通后，断点会出现在这里。"/>}
              </SectionCard>
            ),
          },
          {
            key: 'packages',
            label: <span><FileStack size={14}/> 需求交底</span>,
            children: (
              <SectionCard
                title="甲方需求包"
                subtitle="市场录入 → 商务交底 → 设计回写方案"
                action={
                  <Space>
                    {(workRole === '市场') && <Button type="primary" onClick={() => setReqOpen(true)}>录入需求</Button>}
                  </Space>
                }
              >
                <div className="collab-card-list">
                  {board.packages.map(row => (
                    <article className="collab-card" key={row.id}>
                      <header>
                        <div>
                          <h3>{row.projectName}</h3>
                          <small>v{row.version} · {row.marketOwner}{row.bizOwner ? ` → ${row.bizOwner}` : ''}</small>
                        </div>
                        <Tag color={statusColor[row.status]}>{statusLabel[row.status] || row.status}</Tag>
                      </header>
                      <p>{row.summary}</p>
                      {row.constraints && <p className="muted">约束：{row.constraints}</p>}
                      {row.attachments?.length > 0 && <p className="muted">附件：{row.attachments.join('、')}</p>}
                      {row.schemeNotes ? (
                        <div className="collab-scheme">
                          <strong>方案优化要点</strong>
                          <pre>{row.schemeNotes}</pre>
                          <small>{row.schemeAuthor} · {row.schemeAt}</small>
                        </div>
                      ) : (
                        <p className="muted">尚未回写方案要点</p>
                      )}
                      <Timeline
                        className="collab-history"
                        items={(row.history || []).slice(-4).reverse().map((h: any) => ({
                          children: <span><b>{h.by}</b> {h.action}<small> {h.at}</small></span>,
                        }))}
                      />
                      <footer>
                        {workRole === '商务' && row.status === 'draft' && (
                          <Button size="small" type="primary" icon={<Send size={14}/>} loading={!!busy} onClick={() => void brief(row)}>发布交底</Button>
                        )}
                        {(workRole === '市场' || workRole === '商务') && row.status !== 'draft' && (
                          <Button size="small" onClick={() => void markChanged(row)}>标记需求变更升版</Button>
                        )}
                        {workRole === '设计' && row.status !== 'draft' && (
                          <Button size="small" type="primary" onClick={() => { setSchemeOpen(row); schemeForm.setFieldsValue({schemeNotes: row.schemeNotes || ''}); }}>回写方案要点</Button>
                        )}
                        {workRole === '设计' && row.status !== 'draft' && (
                          <Button size="small" onClick={() => void mutate('/collaboration/contracts', json('POST', {
                            projectName: row.projectName,
                            name: 'BOM/料表交接',
                            trigger: `需求包 ${row.id} 方案回写后`,
                            deliverable: '可采购料表（含规格、数量、需用日期）',
                            slaHours: 24,
                            qualityRule: '料号与图号一一对应；缺项标红',
                            designOwner: '设计',
                            purchaseOwner: '采购',
                            escalateTo: '项目经理',
                            reqPackageId: row.id,
                          })).then(() => setTab('contracts'))}>从本包挂 BOM 契约</Button>
                        )}
                        <small className="muted">ID {row.id}</small>
                      </footer>
                    </article>
                  ))}
                  {!board.packages.length && !loading && <EmptyState icon={<FileStack/>} title="还没有需求包" description="市场角色可录入甲方需求。"/>}
                </div>
              </SectionCard>
            ),
          },
          {
            key: 'contracts',
            label: <span><ClipboardList size={14}/> 接口契约</span>,
            children: (
              <SectionCard
                title="设计 ↔ 采购 接口契约"
                subtitle="先做 BOM/料表交接；超时自动进例外页"
                action={workRole === '设计' ? <Button type="primary" onClick={() => setIfaceOpen(true)}>新建契约</Button> : null}
              >
                <Table
                  rowKey="id"
                  loading={loading}
                  dataSource={board.contracts}
                  pagination={false}
                  columns={[
                    {title: '契约', dataIndex: 'name', render: (n, r) => <div><b>{n}</b><div className="muted">{r.projectName}</div></div>},
                    {title: '触发 / 交付物', render: (_, r) => <div><div>{r.trigger}</div><small>{r.deliverable}</small></div>},
                    {title: '时限', width: 100, render: (_, r) => `${r.slaHours}h`},
                    {title: 'Owner', width: 160, render: (_, r) => <div><div>{r.designOwner}</div><small>{r.purchaseOwner}</small></div>},
                    {title: '状态', width: 110, dataIndex: 'status', render: s => <Tag color={statusColor[s]}>{statusLabel[s] || s}</Tag>},
                    {title: '备注', dataIndex: 'note', ellipsis: true},
                    {title: '操作', width: 220, render: (_, r) => (
                      <Space size={4} wrap>
                        {workRole === '设计' && r.status !== 'delivered' && r.status !== 'closed' && (
                          <Button size="small" onClick={() => void mutate(`/collaboration/contracts/${r.id}`, json('PATCH', {status: 'delivered'}))}>标记已交付</Button>
                        )}
                        {workRole === '采购' && r.status === 'open' && (
                          <Button size="small" onClick={() => void mutate(`/collaboration/contracts/${r.id}`, json('PATCH', {status: 'in_progress', note: '采购已接手'}))}>接手</Button>
                        )}
                        {workRole === '项目经理' && r.status === 'overdue' && (
                          <Button size="small" danger onClick={() => {
                            const stamp = new Date().toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai'});
                            void mutate(`/collaboration/contracts/${r.id}`, json('PATCH', {note: '项目经理已介入催办 · ' + stamp}))
                              .then(() => message.success('已记催办，备注已写入契约'));
                          }}>记催办</Button>
                        )}
                      </Space>
                    )},
                  ]}
                />
              </SectionCard>
            ),
          },
          {
            key: 'bom',
            label: <span><PackageSearch size={14}/> 采购料表</span>,
            children: (
              <SectionCard
                title="料表 / 交期台账"
                subtitle="以契约交付物为唯一待办来源，少另建 Excel"
                action={(workRole === '采购' || workRole === '设计') ? <Button type="primary" onClick={() => setBomOpen(true)}>新增料行</Button> : null}
              >
                <Table
                  rowKey="id"
                  loading={loading}
                  dataSource={board.bom}
                  pagination={false}
                  columns={[
                    {title: '项目', dataIndex: 'projectName', width: 160},
                    {title: '物料', dataIndex: 'materialName', render: (n, r) => <div><b>{n}</b><div className="muted">{r.spec}</div></div>},
                    {title: '数量', dataIndex: 'qty', width: 90},
                    {title: '需用日', dataIndex: 'needBy', width: 110},
                    {title: 'ETA', dataIndex: 'eta', width: 110, render: (eta, r) => workRole === '采购' ? (
                      <Button size="small" type="link" onClick={() => {
                        const v = window.prompt('交期 ETA (YYYY-MM-DD)', eta || '');
                        if (v != null) void mutate(`/collaboration/bom/${r.id}`, json('PATCH', {eta: v, status: r.status === 'pending' ? 'quoted' : r.status, note: r.note || '已回复交期'}));
                      }}>{eta || '填交期'}</Button>
                    ) : (eta || '—')},
                    {title: '状态', dataIndex: 'status', width: 100, render: s => <Tag color={statusColor[s]}>{statusLabel[s] || s}</Tag>},
                    {title: '备注', dataIndex: 'note'},
                    {title: '操作', width: 200, render: (_, r) => workRole === '采购' ? (
                      <Space size={4} wrap>
                        <Button size="small" onClick={() => void mutate(`/collaboration/bom/${r.id}`, json('PATCH', {status: 'quoted', note: r.note || '已询价'}))}>已询价</Button>
                        <Button size="small" onClick={() => void mutate(`/collaboration/bom/${r.id}`, json('PATCH', {status: 'ordered'}))}>已下单</Button>
                        <Button size="small" danger onClick={() => void mutate(`/collaboration/bom/${r.id}`, json('PATCH', {status: 'blocked', note: '催料未回'}))}>阻塞</Button>
                      </Space>
                    ) : null},
                  ]}
                />
              </SectionCard>
            ),
          },
        ]}
      />

      <Modal title="录入甲方需求" open={reqOpen} onCancel={() => setReqOpen(false)} onOk={() => void createReq()} okText="保存草稿" confirmLoading={!!busy}>
        <Form form={reqForm} layout="vertical">
          <Form.Item name="projectName" label="项目" rules={[{required: true, message: '请填写项目'}]}><Input/></Form.Item>
          <Form.Item name="ownerName" label="甲方"><Input/></Form.Item>
          <Form.Item name="summary" label="需求要点" rules={[{required: true, message: '请填写要点'}]}><Input.TextArea rows={3}/></Form.Item>
          <Form.Item name="constraints" label="工期/造价/技术约束"><Input.TextArea rows={2}/></Form.Item>
          <Form.Item name="attachments" label="附件索引（逗号分隔）"><Input.TextArea rows={2}/></Form.Item>
          <Form.Item name="dueHint" label="交底时限提示"><Input placeholder="如：交底后 48h 内回方案"/></Form.Item>
        </Form>
      </Modal>

      <Modal title="回写方案优化要点" open={!!schemeOpen} onCancel={() => setSchemeOpen(null)} onOk={() => void saveScheme()} okText="保存" confirmLoading={!!busy}>
        <Form form={schemeForm} layout="vertical">
          <Form.Item name="schemeNotes" label="方案要点 / 优化建议" rules={[{required: true, message: '请填写方案要点'}]}>
            <Input.TextArea rows={6} placeholder="例如：改用预制支管减少现场焊口；切换窗口内先旁通再切主管…"/>
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="新建设计↔采购契约" open={ifaceOpen} onCancel={() => setIfaceOpen(false)} onOk={() => void createIface()} okText="创建" confirmLoading={!!busy}>
        <Form form={ifaceForm} layout="vertical" initialValues={{name: 'BOM/料表交接', slaHours: 24, designOwner: '设计', purchaseOwner: '采购', escalateTo: '项目经理'}}>
          <Form.Item name="projectName" label="项目" rules={[{required: true}]}><Input/></Form.Item>
          <Form.Item name="name" label="契约名称" rules={[{required: true}]}><Input/></Form.Item>
          <Form.Item name="trigger" label="触发条件" rules={[{required: true}]}><Input/></Form.Item>
          <Form.Item name="deliverable" label="交付物" rules={[{required: true}]}><Input/></Form.Item>
          <Form.Item name="slaHours" label="时限（小时）" rules={[{required: true}]}><Input type="number"/></Form.Item>
          <Form.Item name="qualityRule" label="质量规则"><Input/></Form.Item>
          <Form.Item name="designOwner" label="设计 Owner"><Input/></Form.Item>
          <Form.Item name="purchaseOwner" label="采购 Owner"><Input/></Form.Item>
          <Form.Item name="escalateTo" label="异常升级"><Input/></Form.Item>
          <Form.Item name="reqPackageId" label="关联需求包 ID（可选）"><Input/></Form.Item>
        </Form>
      </Modal>

      <Modal title="新增料表行" open={bomOpen} onCancel={() => setBomOpen(false)} onOk={() => void createBom()} okText="添加" confirmLoading={!!busy}>
        <Form form={bomForm} layout="vertical">
          <Form.Item name="projectName" label="项目" rules={[{required: true}]}><Input/></Form.Item>
          <Form.Item name="materialName" label="物料" rules={[{required: true}]}><Input/></Form.Item>
          <Form.Item name="spec" label="规格"><Input/></Form.Item>
          <Form.Item name="qty" label="数量"><Input/></Form.Item>
          <Form.Item name="needBy" label="需用日期"><Input placeholder="YYYY-MM-DD"/></Form.Item>
          <Form.Item name="supplierHint" label="供应商提示"><Input/></Form.Item>
          <Form.Item name="ifaceId" label="关联契约 ID"><Input/></Form.Item>
          <Form.Item name="reqPackageId" label="关联需求包 ID"><Input/></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
