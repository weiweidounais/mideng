import {useState} from 'react';
import {type FileItem} from './handoff-types';
export type TemplatePhoto=FileItem&{linked_by?:string;linked_at?:string};
function Photo({photo:p,base}:{photo:TemplatePhoto;base:string}){const[failed,setFailed]=useState(false),[attempt,setAttempt]=useState(0);const url='/api'+base+'/template-photos/'+p.id;return <><a href={url} target="_blank" rel="noreferrer">{!failed&&<img src={url+'?attempt='+attempt} alt={p.name} loading="lazy" onError={()=>setFailed(true)}/>}<figcaption>{p.name}</figcaption></a>{failed&&<p role="status">预览失败，原件选择保留。<button type="button" className="text-button" onClick={()=>{setFailed(false);setAttempt(v=>v+1);}}>重试预览</button></p>}</>;}
export function TemplatePhotoGallery({items,base,onRemove,disabled=false}:{items:TemplatePhoto[];base:string;onRemove?:(id:string)=>void;disabled?:boolean}){
 return <div className="template-photos">{items.map(p=><figure key={p.id}><Photo photo={p} base={base}/>{onRemove&&<button type="button" className="text-button" disabled={disabled} onClick={()=>onRemove(p.id)}>移出本次选择</button>}</figure>)}</div>;
}
export function TemplatePhotoPicker({items,base,busy,onUpload,onRemove}:{items:TemplatePhoto[];base:string;busy:boolean;onUpload:(files:File[])=>void;onRemove:(id:string)=>void}){
 return <><label>拍摄模板照片<input type="file" capture="environment" accept="image/jpeg,image/png" disabled={busy} onChange={e=>{const f=e.target.files?.[0];if(f)onUpload([f]);e.target.value='';}}/></label><label>上传模板照片（可多选）<input type="file" accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" multiple disabled={busy} onChange={e=>{const files=Array.from(e.target.files??[]);if(files.length)onUpload(files);e.target.value='';}}/></label><p className="fine">支持JPG、PNG、WebP，每张不超过10MB、2000万像素，每份模板最多10张。照片上传后请核对预览，再确认保存。</p><TemplatePhotoGallery items={items} base={base} disabled={busy} onRemove={onRemove}/></>;
}
