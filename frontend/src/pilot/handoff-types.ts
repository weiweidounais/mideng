export interface FileItem {
    id: string;
    name: string;
    sha256: string;
    size: number;
    media_type: string;
}
export interface BomLine {
    material: string;
    spec: string;
    quantity: string;
    unit: string;
    need_by: string;
}
export interface RequirementData {
    title: string;
    summary: string;
    constraints: string;
    source: string;
    attachment_ids: string[];
    brief_due_at: string | null;
    reply_due_at: string | null;
}
export interface SchemeData {
    title: string;
    notes: string;
    risks: string;
    bom: BomLine[];
    attachment_ids: string[];
    review_reason: string;
}
export type DocData = RequirementData | SchemeData;
export interface BusinessVersion {
    id: string;
    document_id: string;
    number: number;
    source_version_id: string | null;
    previous_id: string | null;
    body: DocData;
    attachments: FileItem[];
    recipients: string[];
    diff_summary: string;
    published_by: string;
    published_at: string;
    current: boolean;
    withdrawn: boolean;
}
export interface BusinessDoc {
    id: string;
    kind: 'requirement' | 'scheme';
    parent_id: string | null;
    source_version_id: string | null;
    revision: number;
    has_draft: boolean;
    version_no: number;
    needs_review: boolean;
    draft: DocData | null;
    draft_files: FileItem[];
    versions: BusinessVersion[];
    created_by: string;
}
export interface Contract {
    id: string;
    version_id: string;
    recipient_id: string;
    proxies: string[];
    created_by: string;
    deliverable: string;
    quality_rule: string;
    require_arrival: boolean;
    sla_hours: number;
    triggered_at: string;
    original_due_at: string;
    due_at: string;
    state: string;
    paused_at: string | null;
    pause_seconds: number;
    return_count: number;
    revision: number;
    overdue: boolean;
    needs_review: boolean;
}
export interface MaterialRow {
    id: string;
    contract_id: string;
    line_no: number;
    material: string;
    spec: string;
    quantity: string;
    unit: string;
    need_by: string;
    arrived: string;
    state: string;
    eta: string | null;
    blocked: boolean;
    note: string;
    revision: number;
}
export interface BusinessIssue {
    id: string;
    object_id: string;
    rule: string;
    owner_id: string;
    title: string;
    active: boolean;
    detected_at: string | null;
    closed_at: string | null;
}
export interface BusinessEvent {
    id: string;
    object_id: string;
    action: string;
    body: Record<string, unknown>;
    actor_id: string;
    at: string;
}
export interface Arrival {
    id: string;
    row_id: string;
    quantity: string;
    occurred_at: string;
    created_by: string;
    created_at: string;
}
export interface Board {
    documents: BusinessDoc[];
    contracts: Contract[];
    rows: MaterialRow[];
    arrivals: Arrival[];
    issues: BusinessIssue[];
    events: BusinessEvent[];
}
export const labels: Record<string, string> = { draft: '草稿', pending: '待交付', submitted: '已提交', accepted: '已验收', closed: '已关闭', cancelled: '已取消', quoted: '已询价', ordered: '已下单', arrived: '已到货' };
export function inputTime(v: string) { return new Date(new Date(v).getTime() + 8 * 3600000).toISOString().slice(0, 16); }
export function isoTime(v: string) { return v ? new Date(v + '+08:00').toISOString() : null; }
