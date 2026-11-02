import { Button, Modal, Tag, Tooltip } from 'antd';
import { RotateCcw, ShieldAlert, Users } from 'lucide-react';
import { useDemand } from './store';
import { bizRoleDescriptions, bizRoleNames, bizRolePeople, contractStatusNames, deliverableStatusNames, packageStatusNames, type BizRole, type ContractStatus, type DeliverableStatus, type PackageStatus } from './types';

const roles: BizRole[] = ['market', 'commercial', 'pm', 'design', 'procurement'];

export function RoleBar() {
  const { role, setRole, reset } = useDemand();
  const confirmReset = () => Modal.confirm({
    title: '重置一期演示数据？',
    content: '将恢复嘉元样例需求包、方案回写与接口契约，覆盖当前浏览器中的演示修改。',
    okText: '恢复样例数据',
    cancelText: '保留当前数据',
    onOk: reset,
  });
  return <section className="demand-rolebar">
    <div className="demand-rolebar-title"><span className="demand-rolebar-icon"><Users size={18} /></span><div><strong>演示角色切换</strong><small>一期按角色走通同一条信息流，数据保存在当前浏览器</small></div></div>
    <div className="demand-role-switch" role="group" aria-label="切换业务演示角色">
      {roles.map((item) => <button key={item} className={role === item ? 'active' : ''} onClick={() => setRole(item)}><span>{bizRoleNames[item]}</span><small>{bizRolePeople[item]}</small></button>)}
    </div>
    <div className="demand-rolebar-side"><span className="demand-role-current"><ShieldAlert size={14} />当前：<b>{bizRoleNames[role]} · {bizRolePeople[role]}</b><small>{bizRoleDescriptions[role]}</small></span><Tooltip title="恢复嘉元样例数据"><Button size="small" icon={<RotateCcw size={13} />} onClick={confirmReset}>重置</Button></Tooltip></div>
  </section>;
}

export function PackageStatusTag({ status, version }: { status: PackageStatus; version?: number }) {
  const color = status === 'briefed' ? 'green' : status === 'changed' ? 'orange' : 'default';
  return <Tag bordered={false} color={color}>{packageStatusNames[status]}{version ? ` · v${version}` : ''}</Tag>;
}

export function ContractStatusTag({ status }: { status: ContractStatus }) {
  const color = status === 'done' ? 'green' : status === 'active' ? 'blue' : status === 'blocked' ? 'red' : 'default';
  return <Tag bordered={false} color={color}>{contractStatusNames[status]}</Tag>;
}

export function DeliverableTag({ status }: { status: DeliverableStatus }) {
  const color = status === 'received' ? 'green' : status === 'submitted' ? 'blue' : status === 'returned' ? 'red' : 'default';
  return <Tag bordered={false} color={color}>{deliverableStatusNames[status]}</Tag>;
}

export function EmptyHint({ title, description }: { title: string; description?: string }) {
  return <div className="demand-empty"><ShieldAlert size={22} /><div><strong>{title}</strong>{description && <p>{description}</p>}</div></div>;
}
