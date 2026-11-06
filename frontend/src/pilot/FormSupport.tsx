import {useEffect,useRef,useState} from 'react';
import {ApiError,checkMutation,pendingMutations,acknowledgeMutation,recoveryIsDurable} from './client';
import {mutationRoute,type ViewRoute} from './navigation';
export function ErrorDetails({error}:{error:unknown}){if(!(error instanceof ApiError))return null;return <div className="field-errors">{error.fieldErrors.length>0&&<ul>{error.fieldErrors.map((e,i)=><li key={i}>{e.field.replace(/^body\./,'')}：{e.message}</li>)}</ul>}{error.requestId&&<small>核对编号：{error.requestId}</small>}</div>;}
export function useDraftGuard(open:boolean,busy:boolean){
 const[dirty,setDirty]=useState(false),completed=useRef(false);
 useEffect(()=>{if(!open){setDirty(false);completed.current=false;}},[open]);
 useEffect(()=>{if(!open)return;const before=(e:BeforeUnloadEvent)=>{if(dirty||busy){e.preventDefault();e.returnValue='';}};const leave=(e:Event)=>{if(completed.current)return;if(busy||(dirty&&!window.confirm('表单尚未提交，离开会丢失本次输入。确定离开？')))e.preventDefault();};window.addEventListener('beforeunload',before);window.addEventListener('mideng-before-navigate',leave);return()=>{window.removeEventListener('beforeunload',before);window.removeEventListener('mideng-before-navigate',leave);};},[open,dirty,busy]);
 return {complete:()=>{completed.current=true;setDirty(false);},mark:()=>{completed.current=false;setDirty(true);},reset:()=>setDirty(false),close:(fn:()=>void)=>{if(!busy&&(!dirty||window.confirm('关闭会丢失尚未提交的输入，确定关闭？'))){setDirty(false);fn();}}};
}

export function RequestRecovery({accountId,onNavigate}:{accountId:string;onNavigate?:(r:ViewRoute)=>void|boolean}){
 const[items,setItems]=useState(()=>pendingMutations()),[message,setMessage]=useState(''),[busy,setBusy]=useState(false);
 useEffect(()=>{const update=()=>setItems(pendingMutations());window.addEventListener('mideng-pending-change',update);update();return()=>window.removeEventListener('mideng-pending-change',update);},[accountId]);
 if(!items.length)return null;
 return <section className="notice request-recovery" role="status"><h2>提交结果待核对</h2><p>请先核对原请求，避免重复提交。仅保存请求编号和摘要，不保存输入原文与文件。</p>{!recoveryIsDurable()&&<p>浏览器暂不能保存恢复编号，请保持当前页并先核对结果；刷新可能丢失本次编号。</p>}{items.map(r=><div key={r.key}><p>{r.phase==='resolved'?'原请求已完成，等待你查看':'原请求尚未确认'} · {new Date(r.at).toLocaleString('zh-CN')} · 编号 {r.key.slice(0,8)}</p><button className="secondary compact" disabled={busy} onClick={()=>{setBusy(true);setMessage('');void checkMutation(r.key).then(()=>setMessage('原请求已完成；保持原表单输入再次确认会读取原结果，也可返回页面查看已完成对象。')).catch(e=>setMessage(e instanceof ApiError&&e.status===404?'尚未找到已提交结果；返回原表单以相同输入重试会复用原编号，请勿改输入新建。':e.message)).finally(()=>setBusy(false));}}>核对原请求</button>{r.phase==='resolved'&&onNavigate&&<button className="primary compact" onClick={()=>{if(onNavigate(mutationRoute(r))!==false)acknowledgeMutation(r.key);}}>查看已完成对象</button>}</div>)}{message&&<p>{message}</p>}</section>;
}
