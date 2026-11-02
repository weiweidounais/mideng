import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { bizRolePeople, type Attachment, type BizRole, type Contract, type ContractStatus, type DeliverableStatus, type DemandState, type RequirementPackage } from './types';
import { seedDemandState } from './seed';

const STORAGE_KEY = 'zhixu:demand-hub:v1';

type PackageInput = {
  projectName: string;
  clientName: string;
  marketOwner: string;
  summary: string;
  schedule: string;
  budget: string;
  technical: string;
  attachments: Attachment[];
};

type ContractInput = {
  packageId: string;
  name: string;
  type: Contract['type'];
  trigger: string;
  deliverable: string;
  dueAt: string;
  quality: string;
  escalation: string;
  owner: string;
  consumer: string;
  urgent: boolean;
  status?: ContractStatus;
};

type SolutionInput = { content: string; optimization: string; risks: string };

interface DemandContextValue {
  role: BizRole;
  setRole: (role: BizRole) => void;
  packages: RequirementPackage[];
  contracts: Contract[];
  createPackage: (input: PackageInput) => RequirementPackage;
  updatePackage: (id: string, input: PackageInput, note: string) => void;
  publishPackage: (id: string, note: string) => void;
  addSolution: (id: string, input: SolutionInput) => void;
  createContract: (input: ContractInput) => Contract;
  updateContractStatus: (id: string, status: ContractStatus, note: string) => void;
  updateDeliverable: (id: string, patch: { deliverableStatus?: DeliverableStatus; promisedDelivery?: string; procurementReply?: string }) => void;
  urgeContract: (id: string, note: string) => void;
  reset: () => void;
  focusPackageId: string;
  setFocusPackageId: (id: string) => void;
  focusContractId: string;
  setFocusContractId: (id: string) => void;
}

const DemandContext = createContext<DemandContextValue | null>(null);

const newId = (prefix: string) => `${prefix}-${crypto.randomUUID()}`;
const nowIso = () => new Date().toISOString();
const clone = <T,>(value: T): T => structuredClone(value);

export const formatDateTime = (value?: string) => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date);
};

export const isOverdue = (contract: Contract) => contract.status !== 'done' && contract.deliverableStatus !== 'received' && new Date(contract.dueAt).getTime() < Date.now();

export const overdueHours = (contract: Contract) => Math.max(0, Math.floor((Date.now() - new Date(contract.dueAt).getTime()) / 3600_000));

const loadState = (): DemandState => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as DemandState;
      if (parsed.schemaVersion === 1 && Array.isArray(parsed.packages) && Array.isArray(parsed.contracts)) return parsed;
    }
  } catch {
    /* fall through to seed */
  }
  return seedDemandState();
};

const diffPackage = (before: RequirementPackage, input: PackageInput) => {
  const changes: string[] = [];
  if (before.projectName !== input.projectName) changes.push(`项目：${before.projectName} → ${input.projectName}`);
  if (before.clientName !== input.clientName) changes.push(`业主：${before.clientName} → ${input.clientName}`);
  if (before.marketOwner !== input.marketOwner) changes.push(`市场负责人：${before.marketOwner} → ${input.marketOwner}`);
  if (before.summary !== input.summary) changes.push('业主要点已更新');
  if (before.schedule !== input.schedule) changes.push('工期约束已更新');
  if (before.budget !== input.budget) changes.push('造价约束已更新');
  if (before.technical !== input.technical) changes.push('技术约束已更新');
  const oldNames = before.attachments.map((item) => item.name).join('|');
  const newNames = input.attachments.map((item) => item.name).join('|');
  if (oldNames !== newNames) changes.push(`附件索引：${before.attachments.length} 项 → ${input.attachments.length} 项`);
  return changes;
};

export function DemandProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<DemandState>(loadState);
  const [focusPackageId, setFocusPackageId] = useState('');
  const [focusContractId, setFocusContractId] = useState('');

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      /* keep the demo usable when storage is unavailable */
    }
  }, [state]);

  const actor = (role: BizRole) => ({ by: bizRolePeople[role], role, at: nowIso() });

  const update = (change: (current: DemandState) => DemandState) => setState((current) => change(clone(current)));

  const setRole = (role: BizRole) => update((current) => ({ ...current, role }));

  const createPackage = (input: PackageInput) => {
    const role = state.role;
    const person = actor(role);
    const maxCode = state.packages.reduce((max, item) => {
      const match = item.code.match(/(\d+)$/);
      return Math.max(max, match ? Number(match[1]) : 0);
    }, 0);
    const item: RequirementPackage = {
      id: newId('pkg'),
      code: `REQ-JY-${new Date().getFullYear()}-${String(maxCode + 1).padStart(3, '0')}`,
      ...input,
      attachments: input.attachments.map((file) => ({ ...file, id: file.id || newId('att') })),
      status: 'draft',
      version: 1,
      createdAt: person.at,
      updatedAt: person.at,
      createdBy: person.by,
      history: [{ id: newId('his'), ...person, action: 'created', version: 1, note: '市场录入甲方需求，等待商务确认交底。', changes: [] }],
    };
    update((current) => ({ ...current, packages: [item, ...current.packages] }));
    return item;
  };

  const updatePackage = (id: string, input: PackageInput, note: string) => {
    const role = state.role;
    const person = actor(role);
    update((current) => ({
      ...current,
      packages: current.packages.map((item) => {
        if (item.id !== id) return item;
        const changes = diffPackage(item, input);
        const version = item.version + 1;
        return {
          ...item,
          ...input,
          attachments: input.attachments.map((file) => ({ ...file, id: file.id || newId('att') })),
          version,
          status: item.status === 'draft' ? 'draft' : 'changed',
          updatedAt: person.at,
          history: [{ id: newId('his'), ...person, action: 'updated', version, note: note || '更新需求包内容。', changes }, ...item.history],
        };
      }),
    }));
  };

  const publishPackage = (id: string, note: string) => {
    const role = state.role;
    const person = actor(role);
    update((current) => ({
      ...current,
      packages: current.packages.map((item) => {
        if (item.id !== id) return item;
        return {
          ...item,
          status: 'briefed',
          briefedAt: person.at,
          briefedBy: person.by,
          updatedAt: person.at,
          history: [{ id: newId('his'), ...person, action: 'briefed', version: item.version, note: note || '确认交底，设计/采购/项目经理可见同一版本。', changes: [] }, ...item.history],
        };
      }),
    }));
  };

  const addSolution = (id: string, input: SolutionInput) => {
    const role = state.role;
    const person = actor(role);
    update((current) => ({
      ...current,
      packages: current.packages.map((item) => {
        if (item.id !== id) return item;
        return {
          ...item,
          solution: { ...input, version: item.version, at: person.at, by: person.by, role },
          updatedAt: person.at,
          history: [{ id: newId('his'), ...person, action: 'solution', version: item.version, note: '设计回写方案优化要点，市场/商务可见。', changes: [] }, ...item.history],
        };
      }),
    }));
  };

  const createContract = (input: ContractInput) => {
    const role = state.role;
    const person = actor(role);
    const maxCode = state.contracts.reduce((max, item) => {
      const match = item.code.match(/(\d+)$/);
      return Math.max(max, match ? Number(match[1]) : 0);
    }, 0);
    const item: Contract = {
      id: newId('con'),
      code: `IC-DP-${new Date().getFullYear()}-${String(maxCode + 1).padStart(3, '0')}`,
      ...input,
      status: input.status || 'active',
      deliverableStatus: 'pending',
      createdAt: person.at,
      updatedAt: person.at,
      history: [{ id: newId('cev'), ...person, action: '创建契约', note: '设计↔采购接口契约已建立，待交接。', from: '新建', to: input.status || 'active' }],
    };
    update((current) => ({ ...current, contracts: [item, ...current.contracts] }));
    return item;
  };

  const updateContractStatus = (id: string, status: ContractStatus, note: string) => {
    const role = state.role;
    const person = actor(role);
    update((current) => ({
      ...current,
      contracts: current.contracts.map((item) => {
        if (item.id !== id || item.status === status) return item;
        return {
          ...item,
          status,
          updatedAt: person.at,
          history: [{ id: newId('cev'), ...person, action: '变更状态', note: note || '更新接口契约状态。', from: item.status, to: status }, ...item.history],
        };
      }),
    }));
  };

  const updateDeliverable = (id: string, patch: { deliverableStatus?: DeliverableStatus; promisedDelivery?: string; procurementReply?: string }) => {
    const role = state.role;
    const person = actor(role);
    update((current) => ({
      ...current,
      contracts: current.contracts.map((item) => {
        if (item.id !== id) return item;
        return {
          ...item,
          ...patch,
          ...(patch.procurementReply ? { procurementReplyAt: person.at } : {}),
          updatedAt: person.at,
          history: [
            {
              id: newId('cev'),
              ...person,
              action: patch.deliverableStatus ? '更新交付物' : '采购回复',
              note: patch.procurementReply || `交付物状态更新为 ${patch.deliverableStatus || item.deliverableStatus}。`,
              ...(patch.deliverableStatus ? { from: item.deliverableStatus, to: patch.deliverableStatus } : {}),
            },
            ...item.history,
          ],
        };
      }),
    }));
  };

  const urgeContract = (id: string, note: string) => {
    const role = state.role;
    const person = actor(role);
    update((current) => ({
      ...current,
      contracts: current.contracts.map((item) => {
        if (item.id !== id) return item;
        return {
          ...item,
          lastUrgedAt: person.at,
          urgent: true,
          updatedAt: person.at,
          history: [{ id: newId('cev'), ...person, action: '催料', note: note || '已催采购回复料表与交期。' }, ...item.history],
        };
      }),
    }));
  };

  const reset = () => {
    setState(seedDemandState());
    setFocusPackageId('');
    setFocusContractId('');
  };

  const value: DemandContextValue = {
    role: state.role,
    setRole,
    packages: state.packages,
    contracts: state.contracts,
    createPackage,
    updatePackage,
    publishPackage,
    addSolution,
    createContract,
    updateContractStatus,
    updateDeliverable,
    urgeContract,
    reset,
    focusPackageId,
    setFocusPackageId,
    focusContractId,
    setFocusContractId,
  };

  return <DemandContext.Provider value={value}>{children}</DemandContext.Provider>;
}

export function useDemand() {
  const value = useContext(DemandContext);
  if (!value) throw new Error('DemandProvider missing');
  return value;
}
