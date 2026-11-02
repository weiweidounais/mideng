import { useMemo, useState } from 'react';
import { Alert, Button, Empty, Segmented, Switch, Tag } from 'antd';
import { AlertTriangle, ArrowRight, BellRing, CalendarClock, CheckCircle2, ClipboardList, FileWarning, GitCompareArrows, ShieldAlert, Sparkles, TimerReset, UserRound } from 'lucide-react';
import { useApp } from '../store';
import { PageTitle, SectionCard } from '../components/ui';
import { formatDateTime, useDemand } from '../demand/store';
import { buildExceptions } from '../demand/exceptions';
import { bizRoleNames, type BizRole, type ExceptionItem, type ExceptionType } from '../demand/types';
import { RoleBar } from '../demand/components';
import './demand.css';

const typeInfo: Record<ExceptionType, { label: string; icon: typeof AlertTriangle; color: string; hint: string }> = {
  undeclared: { label: '需求未交底', icon: ClipboardList, color: 'orange', hint: '商务确认交底后消失' },
  'no-solution': { label: '方案未回写', icon: FileWarning, color: 'orange', hint: '设计回写方案后消失' },
  'version-conflict': { label: '版本冲突', icon: GitCompareArrows, color: 'red', hint: '设计按最新版本重新回写' },
  'material-overdue': { label: '料表超时', icon: TimerReset, color: 'red', hint: '交付物接收或契约完成后消失' },
  'urge-unanswered': { label: '催料未回', icon: BellRing, color: 'purple', hint: '采购回复后消失' },
};

const actionLabel = (item: ExceptionItem, role: BizRole) => {
  if (item.type === 'undeclared') return role === 'commercial' ? '去交底' : '查看需求包';
  if (item.type === 'no-solution') return role === 'design' || role === 'commercial' ? '去回写方案' : '查看需求包';
  if (item.type === 'version-conflict') return role === 'design' || role === 'commercial' ? '处理版本冲突' : '查看差异';
  if (item.type === 'material-overdue') return role === 'procurement' ? '登记料表' : '查看契约';
  return role === 'procurement' ? '回复催料' : '查看契约';
};

export default function ExceptionsPage() {
  const { role } = useDemand();
  const { packages, contracts, setFocusPackageId, setFocusContractId } = useDemand();
  const { navigate } = useApp();
  const [mine, setMine] = useState(false);
  const [level, setLevel] = useState<'all' | 'danger' | 'warning'>('all');
  const [type, setType] = useState<'all' | ExceptionType>('all');

  const all = useMemo(() => buildExceptions(packages, contracts), [packages, contracts]);
  const relevant = mine ? all.filter((item) => item.roles.includes(role)) : all;
  const shown = relevant.filter((item) => (level === 'all' || item.level === level) && (type === 'all' || item.type === type));
  const counts = (Object.keys(typeInfo) as ExceptionType[]).map((key) => ({ key, ...typeInfo[key], count: relevant.filter((item) => item.type === key).length }));
  const danger = relevant.filter((item) => item.level === 'danger').length;

  function open(item: ExceptionItem) {
    if (item.packageId) {
      setFocusPackageId(item.packageId);
      navigate('requirements');
    } else if (item.contractId) {
      setFocusContractId(item.contractId);
      navigate('contracts');
    }
  }

  return <div className="page-content demand-page">
    <PageTitle
      eyebrow="一期 · 例外管理"
      title="例外与待办一页纸"
      description="项目经理为主，市场/商务/设计/采购只看与己相关的断点；所有异常由需求和契约数据自动聚合。"
      actions={<Tag bordered={false} color={danger ? 'red' : 'green'} icon={danger ? <AlertTriangle size={13} /> : <CheckCircle2 size={13} />}>{danger ? `${danger} 项需优先处理` : '暂无高优先级异常'}</Tag>}
    />
    <RoleBar />
    <Alert
      type="info"
      showIcon
      icon={<Sparkles size={16} />}
      message="本期例外页为规则聚合，不使用 AI 自动判断"
      description="需求未交底、方案未回写、版本冲突、料表超时、催料未回均直接来自需求包与接口契约台账；处理完成后自动从列表消失。"
      style={{ marginBottom: 18 }}
    />
    <div className="demand-exception-grid">
      {counts.map(({ key, label, icon: Icon, color, hint, count }) => <button key={key} className={`demand-exception-stat ${type === key ? 'active' : ''}`} onClick={() => setType(type === key ? 'all' : key)}>
        <span className={`demand-metric-icon ${color}`}><Icon size={18} /></span>
        <div><small>{label}</small><strong>{count}</strong><p>{hint}</p></div>
      </button>)}
    </div>
    <SectionCard
      title="待办与断点"
      subtitle="按当前角色过滤；点击处理直接打开对应需求包或契约"
      action={<div className="demand-toolbar"><span className="demand-inline-switch"><Switch size="small" checked={mine} onChange={setMine} />只看与我相关</span><Segmented size="small" value={level} onChange={(value) => setLevel(value as typeof level)} options={[{ value: 'all', label: '全部' }, { value: 'danger', label: '高优先' }, { value: 'warning', label: '提醒' }]} /></div>}
    >
      {shown.length ? <div className="demand-exception-list">{shown.map((item) => { const info = typeInfo[item.type]; const Icon = info.icon; return <article className={`demand-exception-item ${item.level}`} key={item.id}>
        <span className={`demand-exception-icon ${info.color}`}><Icon size={19} /></span>
        <div className="demand-exception-body">
          <div className="demand-exception-title"><Tag bordered={false} color={info.color}>{info.label}</Tag><strong>{item.title}</strong></div>
          <p>{item.detail}</p>
          <div className="demand-exception-meta"><span><UserRound size={13} />{item.owner}</span><span><CalendarClock size={13} />{formatDateTime(item.at)}</span><span><ShieldAlert size={13} />{item.roles.map((roleName) => bizRoleNames[roleName]).join(' / ')} 可见</span></div>
        </div>
        <Button type="primary" ghost icon={<ArrowRight size={14} />} onClick={() => open(item)}>{actionLabel(item, role)}</Button>
      </article>; })}</div> : <Empty description={mine ? `${bizRoleNames[role]}角色下暂无匹配异常，可关闭“只看与我相关”查看全量` : '当前没有匹配的例外 / 待办'} />}
    </SectionCard>
    <SectionCard title="演示路径" subtitle="一期验收口径 1–6 可在浏览器完整走通">
      <div className="demand-demo-steps">
        <div><span>1</span><div><strong>市场录入需求</strong><p>切到市场，录入或编辑需求包；草稿会出现在例外页“需求未交底”。</p></div></div>
        <div><span>2</span><div><strong>商务发布交底</strong><p>切到商务，打开需求包确认交底；设计/采购/项目经理同版本可见。</p></div></div>
        <div><span>3</span><div><strong>设计回写方案</strong><p>切到设计回写方案要点；若需求又变更，例外页会出现版本冲突。</p></div></div>
        <div><span>4</span><div><strong>BOM 契约与采购</strong><p>在契约台账新建或变更 BOM 契约；切到采购登记料表与交期，超时/催料未回自动出现在本页。</p></div></div>
      </div>
    </SectionCard>
  </div>;
}
