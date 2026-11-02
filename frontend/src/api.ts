import {isPrototype} from './mode';
let csrf='';
export class ApiError extends Error { constructor(message:string,public status:number,public data?:unknown){super(message)} }
export function setCsrf(value:string){csrf=value;}
export async function api<T=any>(path:string,options:RequestInit={}):Promise<T>{
 if(isPrototype){const {prototypeApi}=await import('./prototype/api');return prototypeApi<T>(path,options);}
 const headers=new Headers(options.headers);
 if(options.body&&!(options.body instanceof FormData))headers.set('Content-Type','application/json');
 if(options.method&&!['GET','HEAD','OPTIONS'].includes(options.method.toUpperCase()))headers.set('X-CSRF-Token',csrf);
 let response:Response;
 try{response=await fetch('/api'+path,{...options,headers,credentials:'same-origin'})}catch{throw new ApiError('无法连接后端服务，请检查服务是否启动',0)}
 if(!response.ok){const data=await response.json().catch(()=>({}));const raw=data.detail;const detail=Array.isArray(raw)?raw.map((e:any)=>e.msg).join('；'):(raw&&typeof raw==='object'?(raw.message||raw.msg||JSON.stringify(raw)):raw);throw new ApiError(detail||`请求失败（${response.status}）`,response.status,data)}
 if(response.status===204)return undefined as T;
 return response.json();
}
export const json=(method:string,body:unknown):RequestInit=>({method,body:JSON.stringify(body)});
let sessionFlight:Promise<{role:'admin'|'manager'|'user';csrf:string;authenticated:boolean}>|null=null;
export function initializeSession(){if(!sessionFlight)sessionFlight=api<{role:'admin'|'manager'|'user';csrf:string;authenticated:boolean}>('/session').then(value=>{setCsrf(value.csrf);return value}).finally(()=>{sessionFlight=null});return sessionFlight;}
export async function streamChat(body:unknown,onEvent:(event:string,data:any)=>void,signal:AbortSignal){
 if(isPrototype){const {prototypeStreamChat}=await import('./prototype/api');return prototypeStreamChat(body,onEvent,signal);}
 const response=await fetch('/api/chat/stream',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body),signal});
 if(!response.ok){const e=await response.json().catch(()=>({}));throw new ApiError(e.detail||'对话请求失败',response.status)}
 const reader=response.body!.getReader();const decoder=new TextDecoder();let buffer='';
 function consume(frame:string){let event='message';const data:string[]=[];for(const line of frame.split('\n')){if(line.startsWith('event:'))event=line.slice(6).trim();if(line.startsWith('data:'))data.push(line.slice(5).trimStart());}if(data.length){let value:any;try{value=JSON.parse(data.join('\n'))}catch{throw new Error('服务端返回了无效的流式数据')}onEvent(event,value)}}
 try{while(true){const {value,done}=await reader.read();buffer+=decoder.decode(value,{stream:!done}).replaceAll('\r\n','\n');let index;while((index=buffer.indexOf('\n\n'))>=0){consume(buffer.slice(0,index));buffer=buffer.slice(index+2)}if(done){if(buffer.trim())consume(buffer);break}}}finally{reader.releaseLock()}
}
