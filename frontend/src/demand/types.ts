export type BizRole = 'market' | 'commercial' | 'pm' | 'design' | 'procurement';
export type PackageStatus = 'draft' | 'briefed' | 'changed';
export type ContractStatus = 'draft' | 'active' | 'blocked' | 'done';
export type DeliverableStatus = 'pending' | 'submitted' | 'received' | 'returned';

export const bizRoleNames: Record<BizRole, string> = {
  market: '市场',
  commercial: '商务',
  pm: '项目经理',
  design: '设计',
  procurement: '采购',
};

export const bizRolePeople: Record<BizRole, string> = {
  market: '李婉',
  commercial: '陈曦',
  pm: '赵磊',
  design: '周航',
  procurement: '王磊',
};

export const bizRoleDescriptions: Record<BizRole, string> = {
  market: '录入甲方需求与附件索引',
  commercial: '确认交底包并发布变更',
  pm: '看例外与待办断点',
  design: '看需求版本并回写方案',
  procurement: '处理料表与交期待办',
};

export const packageStatusNames: Record<PackageStatus, string> = {
  draft: '草稿',
  briefed: '已交底',
  changed: '有变更',
};

export const contractStatusNames: Record<ContractStatus, string> = {
  draft: '草稿',
  active: '执行中',
  blocked: '已阻塞',
  done: '已完成',
};

export const deliverableStatusNames: Record<DeliverableStatus, string> = {
  pending: '待提交',
  submitted: '已提交',
  received: '已接收',
  returned: '已退回',
};

export interface Attachment {
  id: string;
  name: string;
  kind: string;
  note?: string;
}

export interface Solution {
  content: string;
  optimization: string;
  risks: string;
  version: number;
  at: string;
  by: string;
  role: BizRole;
}

export interface HistoryEntry {
  id: string;
  at: string;
  by: string;
  role: BizRole;
  action: 'created' | 'briefed' | 'updated' | 'solution';
  version: number;
  note: string;
  changes: string[];
}

export interface RequirementPackage {
  id: string;
  code: string;
  projectName: string;
  clientName: string;
  marketOwner: string;
  summary: string;
  schedule: string;
  budget: string;
  technical: string;
  attachments: Attachment[];
  status: PackageStatus;
  version: number;
  createdAt: string;
  updatedAt: string;
  createdBy: string;
  briefedAt?: string;
  briefedBy?: string;
  solution?: Solution;
  history: HistoryEntry[];
}

export interface ContractEvent {
  id: string;
  at: string;
  by: string;
  role: BizRole;
  action: string;
  note: string;
  from?: string;
  to?: string;
}

export interface Contract {
  id: string;
  code: string;
  packageId: string;
  name: string;
  type: 'bom' | 'change' | 'other';
  trigger: string;
  deliverable: string;
  dueAt: string;
  quality: string;
  escalation: string;
  owner: string;
  consumer: string;
  status: ContractStatus;
  deliverableStatus: DeliverableStatus;
  promisedDelivery?: string;
  procurementReply?: string;
  procurementReplyAt?: string;
  lastUrgedAt?: string;
  urgent: boolean;
  createdAt: string;
  updatedAt: string;
  history: ContractEvent[];
}

export interface DemandState {
  schemaVersion: 1;
  role: BizRole;
  packages: RequirementPackage[];
  contracts: Contract[];
}

export type ExceptionType = 'undeclared' | 'no-solution' | 'version-conflict' | 'material-overdue' | 'urge-unanswered';

export interface ExceptionItem {
  id: string;
  type: ExceptionType;
  title: string;
  detail: string;
  owner: string;
  level: 'warning' | 'danger';
  packageId?: string;
  contractId?: string;
  roles: BizRole[];
  at: string;
}
