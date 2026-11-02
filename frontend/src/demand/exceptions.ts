import { formatDateTime, isOverdue, overdueHours } from './store';
import type { Contract, ExceptionItem, RequirementPackage } from './types';

export function buildExceptions(packages: RequirementPackage[], contracts: Contract[]): ExceptionItem[] {
  const items: ExceptionItem[] = [];

  for (const item of packages) {
    if (item.status === 'draft') {
      items.push({
        id: `exc-undeclared-${item.id}`,
        type: 'undeclared',
        title: `需求未交底：${item.projectName}`,
        detail: `${item.code} 仍为草稿（v${item.version}），设计/采购/项目经理看不到正式交底版本。`,
        owner: '商务-陈曦',
        level: 'warning',
        packageId: item.id,
        roles: ['market', 'commercial', 'pm'],
        at: item.updatedAt,
      });
      continue;
    }
    if (!item.solution) {
      items.push({
        id: `exc-no-solution-${item.id}`,
        type: 'no-solution',
        title: `方案未回写：${item.projectName}`,
        detail: `${item.code} 已于 ${formatDateTime(item.briefedAt)} 交底，设计尚未回写方案要点与优化建议。`,
        owner: '设计-周航',
        level: 'warning',
        packageId: item.id,
        roles: ['market', 'commercial', 'pm', 'design'],
        at: item.updatedAt,
      });
      continue;
    }
    if (item.solution.version < item.version) {
      items.push({
        id: `exc-version-${item.id}`,
        type: 'version-conflict',
        title: `版本冲突：${item.projectName}`,
        detail: `方案基于 v${item.solution.version}，需求包已更新到 v${item.version}；市场/商务对甲方沟通前需设计确认口径。`,
        owner: '设计-周航 / 商务-陈曦',
        level: 'danger',
        packageId: item.id,
        roles: ['market', 'commercial', 'pm', 'design'],
        at: item.updatedAt,
      });
    }
  }

  for (const item of contracts) {
    if (isOverdue(item)) {
      items.push({
        id: `exc-material-${item.id}`,
        type: 'material-overdue',
        title: `料表超时：${item.name}`,
        detail: `${item.code} 截止 ${formatDateTime(item.dueAt)}，已超时约 ${overdueHours(item)} 小时；交付物仍为${item.deliverableStatus === 'pending' ? '待提交' : item.deliverableStatus === 'submitted' ? '已提交待接收' : '未完成'}。`,
        owner: item.owner,
        level: 'danger',
        contractId: item.id,
        roles: ['design', 'procurement', 'pm', 'commercial'],
        at: item.updatedAt,
      });
    }
    if (item.status !== 'done' && item.lastUrgedAt && (!item.procurementReplyAt || new Date(item.procurementReplyAt).getTime() < new Date(item.lastUrgedAt).getTime())) {
      items.push({
        id: `exc-urge-${item.id}`,
        type: 'urge-unanswered',
        title: `催料未回：${item.name}`,
        detail: `${formatDateTime(item.lastUrgedAt)} 已催料，采购尚未给出新的料表/交期回复。`,
        owner: '采购-王磊',
        level: 'warning',
        contractId: item.id,
        roles: ['design', 'procurement', 'pm', 'commercial'],
        at: item.lastUrgedAt,
      });
    }
  }

  return items.sort((a, b) => (a.level === b.level ? a.type.localeCompare(b.type) : a.level === 'danger' ? -1 : 1));
}
