export interface Account {
    id: string;
    username: string;
    display_name: string;
    is_admin: boolean;
}
export interface Session {
    account: Account;
    csrf: string;
}
export interface Project {
    id: string;
    code: string;
    name: string;
    revision: number;
    roles: string[];
    actions: string[];
}
export interface Member {
    id: string;
    account_id: string;
    username: string;
    display_name: string;
    roles: string[];
    active: boolean;
    valid_from: string;
    valid_until: string | null;
    revision: number;
}
export interface Audit {
    id: string;
    actor_roles: string[];
    actor_id: string;
    action: string;
    revision: number;
    request_id: string;
    at: string;
}
export interface Todo {
    target_kind?:string|null;
    target_id?:string|null;
    version_id?:string|null;
    id: string;
    project_id: string;
    title: string;
    created_at: string;
}
export type FieldError={field:string;message:string};
export class ApiError extends Error {
    constructor(message:string,readonly status:number,readonly code:string,readonly currentRevision?:number,readonly requestId?:string,readonly fieldErrors:FieldError[]=[]){super(message);}
}
let csrf='',accountScope='';let sessionEpoch=0;
export type PendingMutation={account:string;key:string;path:string;method:string;signature:string;at:string;phase:'waiting'|'unknown'|'resolved';resultId?:string};
const storageKey='mideng.pending.v1',activeWrites=new Set<string>();let memoryRecords:PendingMutation[]=[];let storageFailed=false;
function emitPending(){if(typeof window!=='undefined')window.dispatchEvent(new Event('mideng-pending-change'));}
function records():PendingMutation[]{try{if(!storageFailed&&typeof sessionStorage!=='undefined'){const value=JSON.parse(sessionStorage.getItem(storageKey)??'[]');if(Array.isArray(value))memoryRecords=value.filter(v=>v&&typeof v.account==='string'&&typeof v.key==='string'&&typeof v.path==='string'&&v.path.startsWith('/projects')&&typeof v.signature==='string'&&['waiting','unknown','resolved'].includes(v.phase));}}catch{storageFailed=true;}return memoryRecords;}
function storeRecords(values:PendingMutation[]){memoryRecords=values;try{if(typeof sessionStorage!=='undefined')sessionStorage.setItem(storageKey,JSON.stringify(values));}catch{storageFailed=true;}emitPending();}
function removeRecord(key:string){storeRecords(records().filter(x=>!(x.account===accountScope&&x.key===key)));}
export function recoveryIsDurable(){return !storageFailed;}
export function pendingMutations(){return records().filter(x=>x.account===accountScope&&!activeWrites.has(x.key));}
export function acknowledgeMutation(key:string){removeRecord(key);}
export function setSession(s:Session|null){csrf=s?.csrf??'';accountScope=s?.account?.id??'';sessionEpoch++;emitPending();}
export async function request<T>(path:string,init:RequestInit={}):Promise<T>{
    const headers=new Headers(init.headers);if(typeof init.body==='string'&&!headers.has('Content-Type'))headers.set('Content-Type','application/json');
    if(init.method&&!['GET','HEAD'].includes(init.method))headers.set('X-CSRF-Token',csrf);
    const epoch=sessionEpoch;let response:Response;
    try{response=await fetch('/api'+path,{...init,headers,credentials:'same-origin',signal:init.signal?AbortSignal.any([init.signal,AbortSignal.timeout(15000)]):AbortSignal.timeout(15000)});}
    catch{if(init.signal?.aborted)throw new ApiError('页面读取已停止。',0,'REQUEST_ABORTED');throw new ApiError(init.method&&!['GET','HEAD'].includes(init.method)?'连接中断或超时，提交结果尚未确认，请核对原请求。':'连接中断或超时，当前信息尚未刷新，请恢复连接后重试。',0,'RESULT_UNKNOWN');}
    if(response.status===401&&epoch===sessionEpoch&&csrf){setSession(null);if(typeof window!=='undefined')window.dispatchEvent(new Event('mideng-session-expired'));}
    let body;try{body=await response.json();}catch{throw new ApiError('响应暂不可确认，请按原请求编号核对结果。',response.status,'RESPONSE_INVALID',undefined,response.headers.get('X-Request-ID')??undefined);}
    if(!response.ok){const e=body?.error??{};throw new ApiError(e.message??'请求失败',response.status,e.code??'REQUEST_FAILED',e.current_revision,e.request_id??response.headers.get('X-Request-ID')??undefined,Array.isArray(e.field_errors)?e.field_errors:[]);}
    return body as T;
}
export async function checkMutation(key:string):Promise<{result:Record<string,unknown>}>{
    const value=await request<{result:Record<string,unknown>}>('/requests/'+encodeURIComponent(key));
    storeRecords(records().map(x=>x.account===accountScope&&x.key===key?{...x,phase:'resolved',resultId:typeof value.result.id==='string'?value.result.id:undefined}:x));return value;
}
const digest=async(value:string)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value))),b=>b.toString(16).padStart(2,'0')).join('');
export async function formSignature(form:FormData){const entries=[];for(const [k,v] of form.entries()){if(typeof v==='string')entries.push([k,v]);else entries.push([k,v.name,v.size,Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await v.arrayBuffer())),b=>b.toString(16).padStart(2,'0')).join('')]);}return digest(JSON.stringify(entries));}
async function performMutation<T>(path:string,method:string,body:BodyInit,key:string,signature:string):Promise<T>{
    const scope=accountScope,project=path.match(/^\/projects\/([^/]+)/)?.[1]??'*';const tracked=!!scope&&path.startsWith('/projects');
    const other=tracked?records().find(x=>x.account===scope&&(project==='*'||(x.path.match(/^\/projects\/([^/]+)/)?.[1]??'*')===project)):undefined;
    if(other&&(other.path!==path||other.method!==method||other.signature!==signature||activeWrites.has(other.key)))throw new ApiError('同一项目尚有提交结果待核对，请先核对原请求；当前输入已保留。',0,'RESULT_PENDING');
    const actualKey=other?.key??key;const entry:PendingMutation={account:scope,key:actualKey,path,method,signature,at:other?.at??new Date().toISOString(),phase:'waiting'};
    if(other){try{const found=await checkMutation(actualKey);removeRecord(actualKey);return found.result as T;}catch(e){if(!(e instanceof ApiError)||e.status!==404)throw e;}}
    activeWrites.add(actualKey);if(tracked)storeRecords([...records().filter(x=>!(x.account===scope&&x.key===actualKey)),entry]);
    try{
        const value=await request<T>(path,{method,headers:{'X-Idempotency-Key':actualKey},body});if(tracked)storeRecords(records().filter(x=>!(x.account===scope&&x.key===actualKey)));return value;
    }catch(error){
        const uncertain=error instanceof ApiError&&(error.code==='RESULT_UNKNOWN'||error.code==='RESPONSE_INVALID'||error.status>=500);
        if(uncertain){try{const result=await request<{result:T}>('/requests/'+encodeURIComponent(actualKey));if(tracked)storeRecords(records().filter(x=>!(x.account===scope&&x.key===actualKey)));return result.result;}catch{if(tracked)storeRecords(records().map(x=>x.account===scope&&x.key===actualKey?{...x,phase:'unknown'}:x));throw error;}}
        if(tracked)storeRecords(records().filter(x=>!(x.account===scope&&x.key===actualKey)));throw error;
    }finally{activeWrites.delete(actualKey);emitPending();}
}
export async function mutate<T>(path:string,method:string,body:unknown,key:string):Promise<T>{const text=JSON.stringify(body);return performMutation(path,method,text,key,await digest(text));}
export async function mutateForm<T>(path:string,form:FormData,key:string):Promise<T>{for(const value of form.values())if(typeof value!=='string'&&(!value.size||value.size>20*1024*1024))throw new ApiError('原件须非空且不超过20MB。',422,'FILE_SIZE');return performMutation(path,'POST',form,key,await formSignature(form));}
export function localDate(value:string){return new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});}
